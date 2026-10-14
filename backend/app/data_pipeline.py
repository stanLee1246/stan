"""Observable ODS → DWD → DWS → ADS processing, without private student data."""
from collections import Counter
import hashlib
from itertools import combinations
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .analytics import latest_records
from .auth import administrator
from .crawl_models import CrawlRun, RawCrawlDocument
from .database import get_db
from .models import AuditEvent, IngestionBatch, Opportunity, now
from .pipeline_models import OpportunitySummary, PipelineRefreshRun, SkillAssociation
from .services import normalize_city, normalize_skill
from .school_models import SchoolDataset, UniversitySnapshot, UniversityMajorSnapshot

router = APIRouter(prefix='/api/admin/data-pipeline', tags=['数据处理与仓库'])
VERSION = 'opportunity-pair-v1'
MIN_SAMPLE = 5
MIN_PAIR = 3
MAX_RULES = 100
ERROR_LABELS = {
    'proxy_blocked': '官方来源连接被网络代理阻止', 'robots_disallowed': '来源 robots 规则不允许采集',
    'robots_delay': '来源要求更长的采集间隔', 'robots_unavailable': '无法取得 robots 规则',
    'network_error': '网络连接失败', 'http_error': '来源返回 HTTP 错误',
    'http_status': '官方来源返回 HTTP 限制或错误，采集已停止',
    'robots_missing': '无法核验来源 robots 规则，采集已停止',
    'tls_error': '来源 TLS 验证失败',
    'timeout': '官方来源请求超时', 'dns_failed': '无法解析官方来源域名',
    'private_address': '来源未解析到公共地址，采集已停止', 'unsafe_url': '来源地址未通过范围校验',
    'body_too_large': '网页超过采集大小上限', 'unsupported_content': '来源内容类型不受支持',
    'redirect_failed': '来源重定向无有效目标', 'redirect_limit': '来源重定向超过上限',
    'no_announcements': '未发现可解析公告，请核对栏目模板',
    'consent_missing': '缺少数据使用授权', 'duplicate_conflict': '相同编号存在不同内容',
    'record_validation_failed': '字段、日期或格式未通过校验', 'concurrent_duplicate': '并发导入发生重复',
}


def safe_errors(values):
    """Do not relay arbitrary parser error text, URLs or rejected questionnaire values."""
    result = []
    for error in (values or [])[:20]:
        if not isinstance(error, dict):
            continue
        code = error.get('error_code', error.get('code', 'record_validation_failed'))
        code = code if code in ERROR_LABELS else 'record_validation_failed'
        line = error.get('line')
        result.append({'code': code, 'message': ERROR_LABELS[code],
                       'line': line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else None})
    return result


def safe_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def normalized_records(db, kind):
    result = []
    for item in latest_records(db, kind):
        result.append({'id': item.id, 'version': item.version, 'path': item.path,
                       'city': normalize_city(item.city or '') or '未知',
                       'skills': sorted({normalize_skill(s) for s in item.skills if isinstance(s, str) and s.strip()}),
                       'month': item.published_at.strftime('%Y-%m') if item.published_at else None,
                       'has_deadline': item.deadline is not None})
    return sorted(result, key=lambda row: row['id'])


def fingerprint(records):
    encoded = json.dumps({'version': VERSION, 'records': records}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(encoded.encode()).hexdigest()


def aggregate(records):
    dimensions = {name: Counter() for name in ['path', 'city', 'month', 'skill']}
    pair_counts = Counter()
    known_skills = 0
    for row in records:
        dimensions['path'][row['path']] += 1
        dimensions['city'][row['city']] += 1
        if row['month']:
            dimensions['month'][row['month']] += 1
        dimensions['skill'].update(row['skills'])
        pair_counts.update(combinations(row['skills'], 2))
        known_skills += bool(row['skills'])
    aggregates = {name: [{'key': key, 'count': value} for key, value in sorted(counter.items(), key=lambda i: (-i[1], i[0]))]
                  for name, counter in dimensions.items()}
    rules = []
    if len(records) >= MIN_SAMPLE:
        for (left, right), count in pair_counts.items():
            if count >= MIN_PAIR:
                for antecedent, consequent in [(left, right), (right, left)]:
                    denominator = dimensions['skill'][antecedent]
                    rules.append({'antecedent': antecedent, 'consequent': consequent, 'pair_count': count,
                                  'antecedent_count': denominator, 'population': len(records),
                                  'support': count / len(records), 'confidence': count / denominator})
    rules.sort(key=lambda row: (-row['pair_count'], -row['confidence'], row['antecedent'], row['consequent']))
    mining = {'algorithm': '二项频繁项集 / 有向技能共现规则', 'algorithm_version': VERSION,
              'population': len(records), 'known_skill_population': known_skills,
              'missing_skill_population': len(records) - known_skills,
              'minimum_population': MIN_SAMPLE, 'minimum_pair_count': MIN_PAIR,
              'eligible_rule_count': len(rules), 'stored_rule_count': min(len(rules), MAX_RULES),
              'rule_limit': MAX_RULES, 'status': 'insufficient_sample' if len(records) < MIN_SAMPLE else 'ready',
              'support_definition': '同时提及两项技能的公告数 ÷ 当前范围全部最新公告数（含技能未知公告）',
              'confidence_definition': '同时提及两项技能的公告数 ÷ 提及前项技能的公告数',
              'notice': '反映样本内公告技能共同出现的频率，不代表因果、个人能力或录用概率；缺失技能不等于没有要求。'}
    summary = {'opportunities': len(records), 'known_skill_records': known_skills,
               'publication_unknown': sum(r['month'] is None for r in records),
               'deadline_unknown': sum(not r['has_deadline'] for r in records),
               'city_unknown': sum(r['city'] == '未知' for r in records),
               'skill_mentions': sum(dimensions['skill'].values())}
    return summary, aggregates, mining, rules[:MAX_RULES]


def refresh_warehouse(db, actor_id, kind):
    """Replace DWS + ADS in one transaction; repeats retain a single materialized snapshot."""
    if kind not in ('demo', 'public'):
        raise ValueError('unsupported warehouse scope')
    started = now()
    try:
        previous = db.scalar(select(OpportunitySummary).where(OpportunitySummary.data_kind == kind).with_for_update())
        records = normalized_records(db, kind)
        digest = fingerprint(records)
        summary, aggregates, mining, rules = aggregate(records)
        unchanged = previous is not None and previous.source_fingerprint == digest
        run = PipelineRefreshRun(data_kind=kind, status='unchanged' if unchanged else 'completed',
            source_fingerprint=digest, input_count=len(records), aggregate_count=sum(map(len, aggregates.values())),
            rule_count=len(rules), actor_id=actor_id, started_at=started, finished_at=now())
        db.add(run)
        db.flush()
        if not unchanged:
            db.execute(delete(SkillAssociation).where(SkillAssociation.data_kind == kind))
            source_ids = [r['id'] for r in records]
            raw = list(db.scalars(select(RawCrawlDocument).where(RawCrawlDocument.data_kind == kind,
                                    RawCrawlDocument.opportunity_id.in_(source_ids)))) if source_ids else []
            if previous is None:
                previous = OpportunitySummary(data_kind=kind)
                db.add(previous)
            previous.run_id, previous.source_fingerprint, previous.algorithm_version = run.id, digest, VERSION
            previous.summary, previous.aggregates, previous.mining = summary, aggregates, mining
            previous.refreshed_at = now()
            previous.lineage = {'source_table': 'fact_opportunity_snapshot', 'source_ids': source_ids,
                'source_count': len(records), 'raw_document_ids': [row.id for row in raw],
                'raw_document_count': len(raw), 'version_rule': '来源 URL + 来源记录编号，取当前 data_kind 最新版本',
                'normalization': '同义技能、城市后缀标准化；每条公告技能去重；未知日期保留未知',
                'excluded_inputs': ['个人画像', '问卷原始答案', '账号身份', '逐人校友去向'],
                'target_tables': ['dws_opportunity_summary', 'ads_skill_association']}
            db.add_all(SkillAssociation(data_kind=kind, run_id=run.id, **item) for item in rules)
        db.add(AuditEvent(actor_id=actor_id, action='warehouse_refresh', target_id=run.id))
        db.commit()
        return {'run_id': run.id, 'status': run.status, 'data_kind': kind,
                'opportunities': len(records), 'rules': len(rules), 'refreshed_at': previous.refreshed_at}
    except Exception:
        db.rollback()
        raise


def batch_metadata(batch):
    q = batch.quality or {}
    return {'id': batch.id, 'data_kind': batch.data_kind, 'cleaning_version': batch.cleaning_version,
            'created_at': batch.created_at, 'content_hash': batch.content_hash,
            'total': safe_count(q.get('total')), 'accepted': safe_count(q.get('accepted')),
            'rejected': safe_count(q.get('rejected')), 'duplicates': safe_count(q.get('duplicates')),
            'errors': safe_errors(q.get('errors'))}


@router.get('')
def overview(data_kind: str = Query('public', pattern='^(demo|public)$'),
             user=Depends(administrator), db=Depends(get_db)):
    records = normalized_records(db, data_kind)
    materialized = db.get(OpportunitySummary, data_kind)
    count = lambda model, condition: db.scalar(select(func.count()).select_from(model).where(condition)) or 0
    raw_count = count(RawCrawlDocument, RawCrawlDocument.data_kind == data_kind)
    all_versions = count(Opportunity, Opportunity.data_kind == data_kind)
    batch_count = count(IngestionBatch, IngestionBatch.data_kind == data_kind)
    rules = list(db.scalars(select(SkillAssociation).where(SkillAssociation.data_kind == data_kind)
                           .order_by(SkillAssociation.pair_count.desc(), SkillAssociation.antecedent, SkillAssociation.consequent)))
    crawls = list(db.scalars(select(CrawlRun).where(CrawlRun.data_kind == data_kind).order_by(CrawlRun.id.desc()).limit(10)))
    # Batch metadata spans scopes so authorized questionnaire imports are visible, explicitly labelled and never mined.
    batches = list(db.scalars(select(IngestionBatch).order_by(IngestionBatch.id.desc()).limit(10)))
    runs = list(db.scalars(select(PipelineRefreshRun).where(PipelineRefreshRun.data_kind == data_kind)
                          .order_by(PipelineRefreshRun.id.desc()).limit(10)))
    school_id = db.scalar(select(SchoolDataset.id).order_by(SchoolDataset.id.desc()).limit(1))
    snapshot = None if not materialized else {
        'run_id': materialized.run_id, 'refreshed_at': materialized.refreshed_at,
        'source_fingerprint': materialized.source_fingerprint, 'summary': materialized.summary,
        'aggregates': materialized.aggregates, 'lineage': materialized.lineage, 'mining': materialized.mining,
        'stale': materialized.source_fingerprint != fingerprint(records),
    }
    return {'data_kind': data_kind, 'generated_at': now(), 'snapshot': snapshot,
        'school_data': {'datasets': db.scalar(select(func.count()).select_from(SchoolDataset)) or 0,
                        'universities': count(UniversitySnapshot, UniversitySnapshot.dataset_id == school_id) if school_id else 0,
                        'majors': count(UniversityMajorSnapshot, UniversityMajorSnapshot.dataset_id == school_id) if school_id else 0,
                        'verification_status': 'unverified',
                        'tables': ['raw_school_dataset', 'dim_university_snapshot', 'fact_university_major_snapshot']},
        'storage': 'MySQL 关系型分层仓库原型；云端验证可使用 SQLite，不含 Hadoop/Hive/Spark 集群',
        'layers': [
            {'code': 'ODS', 'name': '原始接入层', 'tables': ['raw_crawl_document', 'ingestion_batch'],
             'rows': raw_count + batch_count, 'unit': '原始网页快照 / 导入批次',
             'description': '保留来源、时间与内容摘要；问卷原文与被拒绝内容不在此页展示。'},
            {'code': 'DWD', 'name': '标准事实层', 'tables': ['fact_opportunity_snapshot'],
             'rows': all_versions, 'unit': '机会历史版本',
             'description': f'当前范围含 {len(records)} 条最新公告；统一城市与技能标签，保留历史版本。'},
            {'code': 'DWS', 'name': '主题汇总层', 'tables': ['dws_opportunity_summary'],
             'rows': 1 if materialized else 0, 'unit': '持久化范围快照',
             'description': '一次事务生成路径、城市、月份、技能统计；只有点击刷新后才更新。'},
            {'code': 'ADS', 'name': '应用结果层', 'tables': ['ads_skill_association'],
             'rows': len(rules), 'unit': '持久化有向技能规则',
             'description': '达到最小样本量和共现次数后生成技能共现结果，可用于学习组合参考。'}],
        'crawls': [{'id': r.id, 'source_id': r.source_id, 'status': r.status, 'data_kind': r.data_kind,
                    'accepted': r.accepted, 'duplicates': r.duplicates, 'rejected': r.rejected,
                    'started_at': r.started_at, 'finished_at': r.finished_at, 'errors': safe_errors(r.errors)} for r in crawls],
        'batches': [batch_metadata(b) for b in batches],
        'batches_notice': '最近 10 个清洗批次覆盖各数据类型，按行标注；授权问卷仅显示处理数量，不进入机会技能挖掘。',
        'rules': [{'antecedent': r.antecedent, 'consequent': r.consequent, 'pair_count': r.pair_count,
                   'antecedent_count': r.antecedent_count, 'population': r.population,
                   'support': r.support, 'confidence': r.confidence} for r in rules],
        'runs': [{'id': r.id, 'status': r.status, 'input_count': r.input_count, 'aggregate_count': r.aggregate_count,
                  'rule_count': r.rule_count, 'started_at': r.started_at, 'finished_at': r.finished_at} for r in runs],
        'application': '当前数据洞察与个人决策仍读取最新机会事实表；本页 DWS/ADS 独立展示可复核的批处理结果，不自动改写个人推荐。',
        'notice': '模拟样本只能说明处理流程，不能用来推断真实市场需求。' if data_kind == 'demo' else '公开来源的采集覆盖与缺失值影响结论，公告条数不是岗位人数。'}


@router.post('/refresh')
def refresh(data_kind: str = Query('public', pattern='^(demo|public)$'), user=Depends(administrator), db=Depends(get_db)):
    try:
        return refresh_warehouse(db, user.id, data_kind)
    except IntegrityError:
        raise HTTPException(409, '另一刷新任务已更新该范围，请重新加载后重试') from None
