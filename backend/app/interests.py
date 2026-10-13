"""Voluntary RIASEC activity interests, role explanations and survey ETL.

The self-authored instrument and prototype thresholds are not validated
psychological tests. No skill, major or career intention is used to infer
activity-interest scores or determine career eligibility.
"""
import csv
import hashlib
import io
import json
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import administrator, current_user
from .database import get_db
from .interest_models import InterestResponse, RoleDisplay
from .models import AuditEvent, IngestionBatch, Profile, now
from .services import normalize_city, normalize_skill

router = APIRouter()
INSTRUMENT_VERSION = 'interest-draft-v1'
RULE_VERSION = 'role-rule-v1'
CLEANING_VERSION = 'survey-v1'
DIMENSIONS = ('R', 'I', 'A', 'S', 'E', 'C')
QUESTION_TEXTS = {
    'R': ['配置设备或工具，使它正常工作', '把学到的知识做成可运行的小系统', '实际操作工具完成明确任务', '排查程序或设备运行问题', '通过动手调整改善一个成果'],
    'I': ['追问一个现象为什么发生', '分析数据寻找规律', '阅读资料比较不同解释', '设计一个小实验检验假设', '钻研没有现成答案的问题'],
    'A': ['设计图像、界面或其他作品', '用不同方式表达一个想法', '为数据选择有故事感的呈现方式', '尝试新的创作形式', '在任务中构思具有个人表达的方案'],
    'S': ['向别人讲解他们不理解的知识', '了解他人的需求并提供支持', '帮助同伴学习一项新工具', '参与以服务他人为目标的活动', '耐心协助别人找到解决办法'],
    'E': ['发起一个项目并邀请他人加入', '展示方案、争取支持', '协调资源推进共同目标', '主动寻找新的合作机会', '在多种方案之间推动形成行动决定'],
    'C': ['按照规则整理资料', '检查表格或记录的准确性', '把重复任务整理成清晰流程', '跟踪进度并做好记录', '按标准维护文档和文件'],
}
QUESTIONS = [{'id': f'{d}{i}', 'dimension': d, 'text': '我喜欢' + text + '。'}
             for d in DIMENSIONS for i, text in enumerate(QUESTION_TEXTS[d], 1)]
QUESTION_IDS = tuple(q['id'] for q in QUESTIONS)
NOTICE = '这是自编的职业活动兴趣探索问卷，尚未完成心理测量效度验证。请填写喜欢程度而非能力强弱；不了解或不想回答可留空。角色仅供本人参考，可以调整或隐藏，不决定职业资格或成功率。'
ROLE_DATA = [
    ('R', '实干小浣熊', ['动手实践', '搭建验证'], '更喜欢操作工具、搭建可用成果和解决实际问题。', ['做一次小型采集或 ETL', '部署本地应用并记录一次排错']),
    ('I', '研究小猫头鹰', ['追问原因', '分析验证'], '更喜欢研究原因、比较解释、分析数据和验证假设。', ['用公开数据完成一个小分析', '阅读一篇方法资料并比较两种解释']),
    ('A', '创意小狐狸', ['创意表达', '多种可能'], '更喜欢设计表达、构思作品和尝试不同呈现方式。', ['制作一张数据故事图', '设计一个交互原型并收集反馈']),
    ('S', '协作小金毛', ['支持他人', '共同成长'], '更喜欢教学、支持、服务以及帮助他人解决问题。', ['给同伴讲解一次新工具', '体验一次助教或志愿服务']),
    ('E', '开拓小狮子', ['发起行动', '推动合作'], '更喜欢发起方案、沟通资源、协调推进和影响决策。', ['发起一个校园小项目', '展示方案并邀请同伴合作']),
    ('C', '规划小企鹅', ['条理清晰', '细节可靠'], '更喜欢按规则整理信息、核对记录、维护流程和跟踪任务。', ['编写一份数据字典', '完成质量核验并整理任务清单']),
    ('U', '探索小兔', ['多路试探', '允许未定'], '当前兴趣接近或还没有突出偏好，也可主动选择继续探索。', ['试做两种不同的短任务', '访谈学长并比较路径条件']),
]
ROLES = [{'code': code, 'name': name, 'tags': tags, 'description': description, 'actions': actions,
          'image_url': '/role-assets/sheet.png', 'sprite_code': code, 'asset_version': 'career-roles-v1'}
         for code, name, tags, description, actions in ROLE_DATA]
ROLE_BY_CODE = {role['code']: role for role in ROLES}
VALID_INTENTS = {'employment', 'postgraduate', 'civil_service', 'public_institution', 'internship'}
CSV_REQUIRED = ['student_key', 'response_id', 'major', 'graduation_year', 'consent', *QUESTION_IDS]
CSV_OPTIONAL = ['skills', 'cities', 'intents']


def normalize_answers(answers):
    if not isinstance(answers, dict) or set(answers) - set(QUESTION_IDS):
        raise ValueError('答案必须使用 R1…C5 的稳定题目编号，不能包含其他题目')
    result = {}
    for key in QUESTION_IDS:
        value = answers.get(key)
        if value is None or isinstance(value, str) and value.strip().lower() in {'', 'unknown', '未知', '不了解', '暂不回答'}:
            result[key] = None
            continue
        if isinstance(value, str) and re.fullmatch('[1-5]', value.strip()):
            value = int(value.strip())
        if type(value) is not int or not 1 <= value <= 5:
            raise ValueError(f'{key} 必须为 1–5 的整数或未知；0 不代表缺失')
        result[key] = value
    return result


def classify_scores(scores, sufficient=True):
    """Use rounded differences so documented boundary equality is reliable."""
    if not sufficient:
        return {'status': 'insufficient_data', 'primary_role': None, 'secondary_role': None,
                'reasons': ['有效回答不足：每维至少 4 题且总计至少 24 题后才计算角色；未知不计为低分。'],
                'actions': ['自愿补充了解的活动题；也可以暂不形成角色']}
    ordered = sorted(DIMENSIONS, key=lambda d: (-scores[d], DIMENSIONS.index(d)))
    first, second = ordered[:2]
    top, runner = scores[first], scores[second]
    gap = round(top - runner, 4)
    if top < 0.60:
        return {'status': 'exploring', 'primary_role': 'U', 'secondary_role': None,
                'reasons': ['当前题目中还没有明显较高的活动偏好，最高维低于原型门槛 0.60；这不代表能力低。'],
                'actions': ['先体验两种短任务，再观察喜欢的活动', '记录一次任务中感兴趣与不感兴趣的部分']}
    if gap < 0.10:
        return {'status': 'multiple_interests', 'primary_role': 'U', 'secondary_role': None,
                'reasons': [f"{ROLE_BY_CODE[first]['name']}与{ROLE_BY_CODE[second]['name']}对应兴趣较接近，前两维差值 {gap:.2f} 小于原型门槛 0.10。", '有多个感兴趣的方向，可以比较体验或自己选择展示角色。'],
                'actions': [ROLE_BY_CODE[first]['actions'][0], ROLE_BY_CODE[second]['actions'][0]]}
    secondary = second if runner >= 0.60 and gap <= 0.20 else None
    reasons = [f"本次自报中，{ROLE_BY_CODE[first]['name']}对应维度为 {top:.2f}，较其他活动更突出；反映喜欢程度而非能力。"]
    if secondary:
        reasons.append(f"{ROLE_BY_CODE[second]['name']}对应维度为 {runner:.2f}，可作为辅助兴趣一起探索。")
    return {'status': 'highlighted_interest', 'primary_role': first, 'secondary_role': secondary,
            'reasons': reasons, 'actions': ROLE_BY_CODE[first]['actions'] + (ROLE_BY_CODE[secondary]['actions'][:1] if secondary else [])}


def score_answers(answers):
    answers = normalize_answers(answers)
    scores, counts = {}, {}
    for dimension in DIMENSIONS:
        values = [answers[f'{dimension}{i}'] for i in range(1, 6) if answers[f'{dimension}{i}'] is not None]
        counts[dimension] = len(values)
        scores[dimension] = round((sum(values) / len(values) - 1) / 4, 4) if len(values) >= 4 else None
    total = sum(counts.values())
    sufficient = total >= 24 and all(count >= 4 for count in counts.values())
    coverage = {'answered_items': total, 'total_items': 30, 'ratio': round(total / 30, 4),
                'by_dimension': counts, 'sufficient': sufficient, 'minimum_per_dimension': 4, 'minimum_total': 24}
    return {'scores': scores, 'coverage': coverage, **classify_scores(scores, sufficient)}


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    instrument_version: str = Field(max_length=40)
    answers: dict = Field(max_length=30)
    consent: StrictBool
    profile_version: int = Field(ge=1, strict=True)
    submission_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('answers')
    @classmethod
    def check_answers(cls, value):
        normalize_answers(value)
        return value


class DisplayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_role: Literal['R', 'I', 'A', 'S', 'E', 'C', 'U'] | None = None
    hidden: StrictBool = False


class SurveyImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_name: str = Field(min_length=2, max_length=120)
    data_kind: Literal['demo', 'authorized'] = 'demo'
    authorized_consent: StrictBool = False
    records: list[dict] = Field(min_length=1, max_length=1000)

    @field_validator('source_name')
    @classmethod
    def check_source(cls, value):
        value = value.strip()
        if len(value) < 2 or value.lower().startswith('self:'):
            raise ValueError('来源名称无效，self: 是保留的本人问卷来源')
        return value


class SurveyCSVImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_name: str = Field(min_length=2, max_length=120)
    data_kind: Literal['demo', 'authorized'] = 'demo'
    authorized_consent: StrictBool = False
    csv_content: str = Field(min_length=1, max_length=500_000)
    field_mapping: dict[str, str] = Field(default_factory=dict, max_length=38)
    ignore_columns: list[str] = Field(default_factory=list, max_length=100)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def record_hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def response_dict(response):
    return {key: getattr(response, key) for key in ['profile_version', 'instrument_version', 'scores', 'coverage',
            'status', 'primary_role', 'secondary_role', 'reasons', 'actions', 'rule_version', 'created_at']} | {
            'response_id': response.id, 'notice': NOTICE}


def latest_response(db, user_id):
    return db.scalar(select(InterestResponse).where(InterestResponse.owner_user_id == user_id,
                     InterestResponse.consent.is_(True)).order_by(InterestResponse.id.desc()))


def role_result(db, user_id):
    response = latest_response(db, user_id)
    if not response:
        return None
    display = db.get(RoleDisplay, user_id)
    override = bool(display and display.manual_override)
    role = display.display_role if override else response.primary_role
    return response_dict(response) | {'display_role': role, 'manual_override': override,
                                     'hidden': bool(display and display.hidden)}


@router.get('/api/interests/instrument')
def instrument():
    return {'version': INSTRUMENT_VERSION, 'rule_version': RULE_VERSION, 'questions': QUESTIONS, 'roles': ROLES,
            'notice': NOTICE, 'scale': {'1': '很不喜欢', '2': '不太喜欢', '3': '一般', '4': '比较喜欢', '5': '很喜欢', 'unknown': '不了解或暂不回答'}}


@router.post('/api/interests/responses', status_code=201)
def submit_answers(payload: AnswerInput, user=Depends(current_user), db=Depends(get_db)):
    if not payload.consent:
        raise HTTPException(422, '需自愿同意将本次答案用于私人职业探索画像')
    if payload.instrument_version != INSTRUMENT_VERSION:
        raise HTTPException(409, '问卷版本已变化，请重新获取题目；旧答案未被修改')
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)))
    if not profile:
        raise HTTPException(422, '请先保存个人信息画像，再填写活动兴趣')
    if profile.version != payload.profile_version:
        raise HTTPException(409, '个人画像版本已变化，请刷新后提交问卷')
    normalized = {'instrument_version': payload.instrument_version, 'answers': normalize_answers(payload.answers), 'profile_version': profile.version, 'consent': True}
    key, source = payload.submission_id or uuid.uuid4().hex, f'self:{user.id}'
    answer_hash = record_hash(normalized)
    existing = db.scalar(select(InterestResponse).where(InterestResponse.source_name == source,
                         InterestResponse.data_kind == 'self_report', InterestResponse.response_key == key))
    if existing:
        if existing.answer_hash != answer_hash:
            raise HTTPException(409, '同一提交编号的答案存在冲突；原测量未被覆盖')
        return response_dict(existing)
    result = score_answers(payload.answers)
    response = InterestResponse(owner_user_id=user.id, profile_id=profile.id, profile_version=profile.version,
        source_name=source, data_kind='self_report', response_key=key, instrument_version=INSTRUMENT_VERSION,
        rule_version=RULE_VERSION, raw_record=payload.model_dump(), normalized_record=normalized,
        answer_hash=answer_hash, consent=True, **result)
    db.add(response)
    try:
        db.flush()
        db.add(AuditEvent(actor_id=user.id, action='interest_measurement', target_id=response.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '问卷被同时提交，请使用同一提交编号重试')
    return response_dict(response)


@router.get('/api/interests/history')
def interest_history(user=Depends(current_user), db=Depends(get_db)):
    return [response_dict(row) for row in db.scalars(select(InterestResponse).where(
            InterestResponse.owner_user_id == user.id).order_by(InterestResponse.id.desc()).limit(50))]


@router.get('/api/profile/roles')
def profile_roles(user=Depends(current_user), db=Depends(get_db)):
    return role_result(db, user.id)


@router.patch('/api/profile/roles/display')
def update_display(payload: DisplayInput, user=Depends(current_user), db=Depends(get_db)):
    if not latest_response(db, user.id):
        raise HTTPException(422, '尚无问卷结果，请先自愿填写问卷')
    display = db.get(RoleDisplay, user.id)
    if not display:
        display = RoleDisplay(user_id=user.id)
        db.add(display)
    display.display_role, display.manual_override = payload.display_role, payload.display_role is not None
    display.hidden, display.updated_at = payload.hidden, now()
    db.add(AuditEvent(actor_id=user.id, action='interest_role_display', target_id=user.id))
    db.commit()
    return role_result(db, user.id)


@router.delete('/api/interests/responses/{response_id}')
def withdraw_response(response_id: int, user=Depends(current_user), db=Depends(get_db)):
    # Import locally: the decision feature imports role_result for explanations.
    from .decision_models import DecisionRun

    response = db.get(InterestResponse, response_id)
    if not response or response.owner_user_id != user.id:
        raise HTTPException(404, '本人问卷记录不存在')
    deleted_decision_runs = 0
    for run in db.scalars(select(DecisionRun).where(DecisionRun.user_id == user.id)):
        if (run.results or {}).get('interest_response_id') == response_id:
            # Delete the immutable snapshot as a whole instead of rewriting its
            # recorded evidence. Action progress lives in the same row.
            db.delete(run)
            deleted_decision_runs += 1
    db.delete(response)
    if not db.scalar(select(InterestResponse).where(InterestResponse.owner_user_id == user.id,
                      InterestResponse.id != response_id).limit(1)):
        display = db.get(RoleDisplay, user.id)
        if display:
            db.delete(display)
    db.add(AuditEvent(actor_id=user.id, action='interest_withdrawal', target_id=response_id))
    db.commit()
    return {'message': f'本次私人问卷、原始答案和角色计算记录已删除；同时删除 {deleted_decision_runs} 份引用本次测量的决策记录及其行动进度。已删除决策链接将返回不存在，请重新生成方案。',
            'deleted_decision_runs': deleted_decision_runs, 'current_role': role_result(db, user.id)}


def normalize_terms(value, kind):
    if value is None or value == '':
        return []
    if isinstance(value, str):
        value = value.split('|')
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError(f'{kind} 最多 30 个标签')
    if any(not isinstance(term, str) or len(term.strip()) > 80 for term in value):
        raise ValueError(f'{kind} 标签格式或长度无效')
    values = [term.strip() for term in value if term.strip()]
    if kind == 'skills':
        values = [normalize_skill(term) for term in values]
    if kind == 'cities':
        values = [normalize_city(term) for term in values]
    if kind == 'intents' and set(values) - VALID_INTENTS:
        raise ValueError('intents 必须是支持的发展路径代码')
    return sorted(set(values))


def normalize_external_record(row):
    allowed = {'response_id', 'student_key', 'major', 'graduation_year', 'skills', 'cities', 'intents', 'answers', 'consent'}
    if set(row) - allowed:
        raise ValueError('包含模板以外的字段；不得导入姓名、联系方式或账户编号')
    if row.get('consent') is not True:
        raise ValueError('该记录缺少本人自愿问卷授权 consent=true')
    key = row.get('student_key')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', key.strip()):
        raise ValueError('student_key 必须为 6–64 位随机匿名标识')
    response_id = row.get('response_id')
    if not isinstance(response_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', response_id.strip()):
        raise ValueError('response_id 必须为 1–100 位字母、数字、下划线或连字符')
    major = row.get('major')
    if major is None or major == '':
        major = None
    elif not isinstance(major, str) or not 2 <= len(major.strip()) <= 100:
        raise ValueError('专业名称应为 2–100 个字符或留空')
    else:
        major = major.strip()
    year = row.get('graduation_year')
    if year is None or year == '':
        year = None
    else:
        if type(year) is int:
            pass
        elif isinstance(year, str) and re.fullmatch(r'\d{4}', year.strip()):
            year = int(year.strip())
        else:
            raise ValueError('graduation_year 必须为四位年份或未知')
        if not 2000 <= year <= 2100:
            raise ValueError('毕业届次必须在 2000–2100 年之间')
    return {'response_id': response_id.strip(), 'student_key': key.strip(), 'major': major, 'graduation_year': year,
            'skills': normalize_terms(row.get('skills'), 'skills'), 'cities': normalize_terms(row.get('cities'), 'cities'),
            'intents': normalize_terms(row.get('intents'), 'intents'), 'answers': normalize_answers(row.get('answers')),
            'consent': True, 'instrument_version': INSTRUMENT_VERSION}


def import_surveys(db, user_id, payload: SurveyImport, raw_content=None, line_offset=1, source_file_hash=None, export_metadata=None):
    if payload.data_kind == 'authorized' and not payload.authorized_consent:
        raise HTTPException(422, '真实问卷需确认已取得本人授权，并使用随机匿名标识')
    supplied = canonical_json(payload.model_dump()) if raw_content is None else raw_content
    if len(supplied.encode('utf-8')) > 500_000:
        raise HTTPException(413, '每批原始载荷不得超过 500 KB，请分批导入')
    source_file_hash = source_file_hash or hashlib.sha256(supplied.encode('utf-8')).hexdigest()
    # Raw input, including a CSV override, is used only for size/hash checks.
    # Consent and record validation precede retention. Rejected records never
    # enter batch raw_content or InterestResponse.raw_record.
    retained_records, rejected_metadata = [], []
    empty_raw = canonical_json({'records': [], 'rejected_rows': []})
    batch = IngestionBatch(source_name=payload.source_name, data_kind=payload.data_kind,
                          content_hash=hashlib.sha256(empty_raw.encode('utf-8')).hexdigest(), raw_content=empty_raw,
                          cleaning_version=CLEANING_VERSION, imported_by=user_id)
    db.add(batch)
    db.flush()
    quality = {'total': len(payload.records), 'accepted': 0, 'rejected': 0, 'duplicates': 0, 'errors': [],
               'cleaning_version': CLEANING_VERSION, 'instrument_version': INSTRUMENT_VERSION,
               'role_rule_version': RULE_VERSION, 'answered_items': 0, 'total_items': 30 * len(payload.records),
               'role_statuses': {}, 'notice': '模拟问卷不代表真实学生兴趣分布' if payload.data_kind == 'demo' else '授权匿名问卷不关联站内账户'}
    if source_file_hash:
        quality['source_file_hash'] = source_file_hash
        quality['export_metadata'] = export_metadata or {}
    for line, row in enumerate(payload.records, line_offset):
        error_code = 'record_validation_failed'
        try:
            if row.get('consent') is not True:
                error_code = 'consent_missing'
            normalized = normalize_external_record(row)
            digest = record_hash(normalized)
            existing = db.scalar(select(InterestResponse).where(InterestResponse.source_name == payload.source_name,
                        InterestResponse.data_kind == payload.data_kind, InterestResponse.response_key == normalized['response_id']))
            if existing:
                if existing.answer_hash != digest:
                    error_code = 'duplicate_conflict'
                    raise ValueError('同一来源、数据类型与问卷编号存在冲突；原记录未覆盖')
                quality['duplicates'] += 1
                retained_records.append({'line': line, 'raw_record': row})
                continue
            result = score_answers(normalized['answers'])
            response = InterestResponse(source_name=payload.source_name, data_kind=payload.data_kind,
                       response_key=normalized['response_id'], student_key=normalized['student_key'],
                       instrument_version=INSTRUMENT_VERSION, rule_version=RULE_VERSION, batch_id=batch.id,
                       raw_record=row, normalized_record=normalized, answer_hash=digest, consent=True, **result)
            # The savepoint prevents a concurrent duplicate from invalidating earlier accepted rows.
            try:
                with db.begin_nested():
                    db.add(response)
                    db.flush()
            except IntegrityError:
                error_code = 'concurrent_duplicate'
                raise ValueError('问卷编号被同时导入，请重试；已有记录未覆盖')
            quality['accepted'] += 1
            retained_records.append({'line': line, 'raw_record': row})
            quality['answered_items'] += result['coverage']['answered_items']
            status = result['status']
            quality['role_statuses'][status] = quality['role_statuses'].get(status, 0) + 1
        except ValueError as exc:
            quality['rejected'] += 1
            rejected_metadata.append({'line': line, 'error_code': error_code})
            if len(quality['errors']) < 100:
                quality['errors'].append({'line': line, 'reason': str(exc), 'error_code': error_code})
    accepted_cells = quality['accepted'] * 30
    quality['answer_completeness'] = round(quality['answered_items'] / accepted_cells, 4) if accepted_cells else None
    quality['errors_truncated'] = quality['rejected'] > len(quality['errors'])
    retained_raw = canonical_json({'records': retained_records, 'rejected_rows': rejected_metadata})
    batch.raw_content = retained_raw
    batch.content_hash = hashlib.sha256(retained_raw.encode('utf-8')).hexdigest()
    batch.quality = quality
    db.add(AuditEvent(actor_id=user_id, action='import_surveys', target_id=batch.id))
    db.commit()
    return {'batch_id': batch.id, 'quality': quality}


@router.post('/api/admin/import/surveys')
def import_survey_json(payload: SurveyImport, user=Depends(administrator), db=Depends(get_db)):
    return import_surveys(db, user.id, payload)


@router.post('/api/admin/import/surveys/csv')
def import_survey_csv(payload: SurveyCSVImport, user=Depends(administrator), db=Depends(get_db)):
    if len(payload.csv_content.encode('utf-8')) > 500_000:
        raise HTTPException(413, '每批原始载荷不得超过 500 KB，请分批导入')
    reader = csv.DictReader(io.StringIO(payload.csv_content.lstrip('\ufeff')), strict=True)
    columns = reader.fieldnames
    if not columns or len(set(columns)) != len(columns) or any(len(column) > 300 for column in columns):
        raise HTTPException(422, 'CSV 表头缺失、重复或过长，请先确认 UTF-8 导出格式')
    mapping, ignored, export_mode = export_column_mapping(columns, payload)
    records = []
    try:
        for row in reader:
            if len(records) >= 1000:
                raise HTTPException(422, '每批应包含 1–1000 条问卷')
            if None in row or any(row.get(column) is None for column in columns):
                # A malformed row gets rejection metadata only, never raw retention.
                records.append({'invalid_columns': True})
                continue
            record = {canonical: row[header] for canonical, header in mapping.items() if canonical not in QUESTION_IDS and canonical != 'consent'}
            record['answers'] = {key: row[mapping[key]] if key in mapping else None for key in QUESTION_IDS}
            record['consent'] = row[mapping['consent']].strip().lower() in {'true', '是', '同意', '已授权'}
            if export_mode:
                # Stable source-scoped pseudonyms; never retain an exported identity in raw storage.
                raw_id = record.get('response_id', '').strip()
                identity = (record.get('student_key') or raw_id).strip()
                record['response_id'] = 'export_' + hashlib.sha256((payload.source_name.strip() + '\0' + raw_id).encode()).hexdigest()[:40] if raw_id else ''
                record['student_key'] = 'anon_' + hashlib.sha256((payload.source_name.strip() + '\0' + identity).encode()).hexdigest()[:40] if identity else ''
            records.append(record)
    except csv.Error:
        raise HTTPException(422, 'CSV 格式损坏，请使用 UTF-8 模板')
    if not records:
        raise HTTPException(422, '每批应包含 1–1000 条问卷')
    try:
        normalized_payload = SurveyImport(source_name=payload.source_name, data_kind=payload.data_kind,
                    authorized_consent=payload.authorized_consent, records=records)
    except ValueError:
        raise HTTPException(422, '来源名称无效，self: 为本人问卷保留来源')
    # Only whitelisted mapped fields reach storage. The hash preserves file provenance
    # without storing ignored names, phone numbers, IP addresses or timestamps.
    return import_surveys(db, user.id, normalized_payload, raw_content=canonical_json(records), line_offset=2,
            source_file_hash=hashlib.sha256(payload.csv_content.encode()).hexdigest(),
            export_metadata={'mapped_fields': sorted(mapping), 'ignored_column_count': len(ignored),
                             'source_scoped_pseudonyms': export_mode, 'raw_policy': 'validated_consenting_records_only'})


EXPORT_ALIASES = {
    'student_key': ['匿名编号', '匿名标识'], 'response_id': ['答卷编号', '答卷ID', '序号', '回应编号'],
    'major': ['专业', '所学专业'], 'graduation_year': ['毕业年份', '毕业届次', '预计毕业年份'],
    'consent': ['授权', '同意授权', '知情同意'],
}
PERSONAL_COLUMN_PATTERNS = ('姓名', '电话', '手机', '邮箱', '身份证', '微信', 'QQ', '地址', '学号', 'IP', 'name', 'phone', 'email', 'contact')


def personal_column(header):
    lowered = header.lower()
    return any(pattern.lower() in lowered for pattern in PERSONAL_COLUMN_PATTERNS)


def export_column_mapping(columns, payload):
    allowed = set(CSV_REQUIRED + CSV_OPTIONAL)
    if set(payload.field_mapping) - allowed:
        raise HTTPException(422, 'field_mapping 的键只能是模板规范字段或 R1…C5')
    if any(header not in columns for header in payload.field_mapping.values()):
        raise HTTPException(422, 'field_mapping 指定的导出表头不存在，请逐字匹配导出列标题')
    if len(set(payload.field_mapping.values())) != len(payload.field_mapping):
        raise HTTPException(422, '一个导出列不能映射到多个题目或字段')
    if any(personal_column(header) for header in payload.field_mapping.values()):
        raise HTTPException(422, '不能映射姓名、联系方式、学号或 IP 字段；使用匿名编号或答卷序号')
    if any(header not in columns for header in payload.ignore_columns):
        raise HTTPException(422, 'ignore_columns 包含导出文件中不存在的列')
    mapping = dict(payload.field_mapping)
    occupied = set(mapping.values())
    for canonical in CSV_REQUIRED + CSV_OPTIONAL:
        if canonical in mapping:
            continue
        candidates = [canonical, *EXPORT_ALIASES.get(canonical, [])]
        matches = [header for header in candidates if header in columns and header not in occupied]
        if len(matches) > 1:
            raise HTTPException(422, f'{canonical} 存在多个可映射列，请用 field_mapping 指定其中一个')
        if matches:
            mapping[canonical] = matches[0]
            occupied.add(matches[0])
    export_mode = bool(payload.field_mapping) or any(key != value for key, value in mapping.items())
    required = {'response_id', 'consent'} if export_mode else set(CSV_REQUIRED)
    missing = required - set(mapping)
    if missing:
        raise HTTPException(422, '缺少必须映射字段：' + ', '.join(sorted(missing)) + '。问卷授权列需明确同意，不能由导入者代替作答。')
    if export_mode and not any(key in mapping for key in QUESTION_IDS):
        raise HTTPException(422, '需至少映射一道活动兴趣题；未映射题目作为未知，不会补成 0 或中立分')
    if set(payload.ignore_columns) & occupied:
        raise HTTPException(422, '同一列不能同时映射并忽略')
    ignored = set(payload.ignore_columns) | {header for header in columns if personal_column(header)}
    unhandled = set(columns) - occupied - ignored
    if unhandled:
        raise HTTPException(422, '存在未处理的导出列，请通过 field_mapping 对应题目或在 ignore_columns 明确忽略；列标题：' + ', '.join(sorted(unhandled)[:10]))
    return mapping, ignored, export_mode


def seed_demo_surveys(db, admin_user_id):
    """Deterministic anonymous fixtures, never invented questionnaire answers for users."""
    records = []
    for i in range(42):
        peak = DIMENSIONS[i % 6]
        answers = {key: (5 if key.startswith(peak) else 2 + (i % 2)) for key in QUESTION_IDS}
        if i % 7 == 6:
            answers = {key: 4 for key in QUESTION_IDS}
        records.append({'response_id': f'demo-survey-{i:04}', 'student_key': f'synthetic_{i:06}',
                        'major': '数据科学与大数据技术' if i < 30 else '软件工程', 'graduation_year': 2027 + i % 2,
                        'skills': ['python', 'SQL'], 'cities': ['衡阳市'], 'intents': ['employment', 'postgraduate'],
                        'answers': answers, 'consent': True})
    return import_surveys(db, admin_user_id, SurveyImport(source_name='演示问卷：非真实学生测量', data_kind='demo', records=records))
