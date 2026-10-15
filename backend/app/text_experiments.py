"""Read-only, owner-private rule/TF-IDF comparison with auditable lexical evidence."""
from collections import Counter
import hashlib
import html
import json
import math
import re
import time
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from .auth import current_user
from .database import get_db
from .decisions import compare_opportunity, latest_statement
from .models import Profile, now
from .services import PATH_LABELS, normalize_skill, profile_dict

router = APIRouter(prefix='/api/experiments', tags=['推荐方法对照'])
MODEL_VERSION = 'lexical-tfidf-comparison-v1'
CANDIDATE_LIMIT = 100
DESCRIPTION_LIMIT = 4000
DEFAULT_WEIGHTS = {'skills': 0.5, 'city': 0.3, 'major': 0.2}
STOPWORDS = frozenset('the and with for this that from are you your our have has will can a an to of in on is be or as at by it'.split())
CHINESE_STOPWORDS = frozenset(['我们', '你们', '他们', '进行', '以及', '相关', '工作', '负责', '要求', '具备', '具有', '熟悉', '掌握', '能力', '招聘', '岗位', '单位', '专业', '欢迎', '需要', '以上', '以下', '其他'])
TOKEN_RE = re.compile(r'[a-z][a-z0-9]*(?:[+#]+)?|[\u3400-\u9fff]+')
NOTICE = ('本页在同一路径、同一候选集上对照结构化规则与 TF-IDF 词面相似度。'
          '两者的量纲和依据不同，不相加，也不代表录用或升学概率。'
          '没有真实相关性标注，暂不计算准确率、Precision、Recall 或 NDCG；兴趣角色及心理特征不参与计算。')


def tokenize(text):
    """NFKC/case normalization; English identifiers and Chinese adjacent bigrams."""
    normalized = unicodedata.normalize('NFKC', html.unescape(str(text or ''))).lower()
    normalized = re.sub(r'<[^>]{0,1000}>', ' ', normalized)
    terms = []
    for chunk in TOKEN_RE.findall(normalized):
        if chunk[0].isascii():
            if chunk not in STOPWORDS:
                terms.append(chunk)
        else:
            # No cross-punctuation n-grams and no pretend Chinese linguistic segmentation.
            terms.extend(chunk[i:i + 2] for i in range(len(chunk) - 1)
                         if chunk[i:i + 2] not in CHINESE_STOPWORDS)
    return terms


def idf_weights(documents):
    """Same smooth-IDF equation as sklearn: log((1+n)/(1+df)) + 1."""
    frequencies = Counter(term for document in documents for term in document)
    return {term: math.log((1 + len(documents)) / (1 + count)) + 1
            for term, count in sorted(frequencies.items())}


def weighted_vector(counts, idf):
    vector = {term: (1 + math.log(count)) * idf[term]
              for term, count in counts.items() if term in idf and count > 0}
    norm = math.sqrt(sum(value * value for value in vector.values()))
    return {term: value / norm for term, value in vector.items()} if norm else {}


def cosine_contributions(query, document):
    """Input vectors are L2-normalized; products explain the entire dot product."""
    contributions = [(term, query[term] * document[term]) for term in query.keys() & document.keys()]
    contributions.sort(key=lambda pair: (-pair[1], pair[0]))
    return min(1.0, max(0.0, sum(value for _, value in contributions))), contributions


def document_text(item):
    # City is deliberately absent: it belongs to explicit preferences in the rule model.
    return '\n'.join([item.title or '', ' '.join(normalize_skill(s) for s in (item.skills or [])),
                      (item.description or '')[:DESCRIPTION_LIMIT]])


def competition_ranks(rows, key, eligible=lambda value: value is not None):
    scores = sorted([row[key] for row in rows if eligible(row[key])], reverse=True)
    return {row['opportunity']['id']: scores.index(row[key]) + 1 if eligible(row[key]) else None
            for row in rows}


def compare_text_models(db, profile, data_kind):
    started = time.perf_counter()
    values = profile_dict(profile)
    latest = latest_statement(data_kind)
    latest_count = db.scalar(select(func.count()).select_from(latest.subquery())) or 0
    pool, inspected, excluded = [], 0, Counter()
    capped = False
    # Stream newest snapshots and apply identical hard exclusions before fitting either model.
    for item in db.scalars(latest.order_by(latest.selected_columns.id.desc()).execution_options(yield_per=100)):
        inspected += 1
        structured = compare_opportunity(values, item, DEFAULT_WEIGHTS)
        if structured['eligibility'] == 'ineligible':
            for reason in structured['exclusion_reasons']:
                excluded[reason] += 1
            continue
        if len(pool) == CANDIDATE_LIMIT:
            capped = True
            break
        pool.append((item, structured))
    skills = [normalize_skill(s) for s in values['skills'] if s.strip()]
    summary = values['summary'].strip()
    query_terms = Counter(tokenize(' '.join(skills) + '\n' + summary))
    paths = []
    for path in values['intents']:
        candidates = [(item, row) for item, row in pool if item.path == path]
        texts = [document_text(item) for item, _ in candidates]
        documents = [Counter(tokenize(text)) for text in texts]
        idf = idf_weights(documents)
        query_vector = weighted_vector(query_terms, idf)
        rows = []
        fingerprint_parts = []
        for (item, structured), text, counts in zip(candidates, texts, documents):
            vector = weighted_vector(counts, idf)
            similarity, contributions = cosine_contributions(query_vector, vector)
            text_score = round(similarity, 8) if query_vector and vector else None
            matched = [{'term': term, 'contribution': round(value, 10),
                        'query_count': query_terms[term], 'document_count': counts[term],
                        'idf': round(idf[term], 10)} for term, value in contributions[:8]]
            shown = sum(value for _, value in contributions[:8])
            row = {'opportunity': structured['opportunity'], 'eligibility': structured['eligibility'],
                   'rule_score': structured['score'], 'rule_components': structured['components'],
                   'rule_observed_weight': structured['observed_weight'],
                   'text_similarity': text_score, 'matched_terms': matched,
                   'contribution_sum': round(similarity, 8) if text_score is not None else None,
                   'unshown_contribution': round(max(0, similarity - shown), 10),
                   'missing_rule_dimensions': [part['label'] for part in structured['components'] if part['value'] is None],
                   'text_status': ('query_without_corpus_terms' if not query_vector else
                                   'document_without_terms' if not vector else
                                   'shared_terms' if contributions else 'no_shared_terms'),
                   'description_truncated': len(item.description or '') > DESCRIPTION_LIMIT}
            rows.append(row)
            fingerprint_parts.append({'id': item.id, 'version': item.version,
                                      'text_hash': hashlib.sha256(text.encode()).hexdigest()})
        rule_ranks = competition_ranks(rows, 'rule_score')
        text_ranks = competition_ranks(rows, 'text_similarity', lambda v: v is not None and v > 0)
        for row in rows:
            item_id = row['opportunity']['id']
            row['rule_rank'], row['text_rank'] = rule_ranks[item_id], text_ranks[item_id]
        rows.sort(key=lambda row: (row['rule_rank'] is None, row['rule_rank'] or 0, row['opportunity']['id']))
        query_in_vocabulary = sorted(query_terms.keys() & idf.keys())
        paths.append({'path': path, 'label': PATH_LABELS.get(path, path), 'candidate_count': len(rows),
                      'vocabulary_size': len(idf), 'query_terms_in_vocabulary': query_in_vocabulary,
                      'query_term_coverage': {'matched_distinct': len(query_in_vocabulary), 'distinct': len(query_terms)},
                      'text_ranked_count': sum(row['text_rank'] is not None for row in rows),
                      'rule_ranked_count': sum(row['rule_rank'] is not None for row in rows),
                      'corpus_fingerprint': hashlib.sha256(json.dumps(fingerprint_parts, sort_keys=True).encode()).hexdigest(),
                      'comparisons': rows})
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    return {'model_version': MODEL_VERSION, 'profile_version': profile.version, 'data_kind': data_kind,
            'generated_at': now(),
            'query': {'skills': skills, 'summary': summary, 'terms': sorted(query_terms),
                      'evidence_present': bool(query_terms),
                      'fingerprint': hashlib.sha256(json.dumps(sorted(query_terms.items()), ensure_ascii=False).encode()).hexdigest(),
                      'notice': '文本查询只用已保存的技能和项目经历；专业、学历、意向用于资格过滤，城市仅用于规则比较。'
                                '仅填写专业不会被当作职业偏好。'},
            'scope': {'latest_in_scope': latest_count, 'inspected_snapshots': inspected,
                      'evaluated_candidates': len(pool), 'candidate_limit': CANDIDATE_LIMIT,
                      'candidate_cap_reached': capped, 'excluded_reason_counts_inspected': dict(excluded),
                      'exclusion_counts_complete': not capped,
                      'version_rule': '同一数据类型、来源 URL、记录编号仅保留最高版本，再按最新记录 ID 取最多100条符合已知条件的候选',
                      'eligibility_rule': '排除明确已过期、专业不符、学历不足、当前意向之外的机会；未知条件保留待核对',
                      'count_note': '达到上限时，排除统计仅覆盖已检查快照；多项排除原因可来自同一条记录。每条路径独立拟合IDF和排序。'},
            'parameters': {'rule_weights': DEFAULT_WEIGHTS, 'idf': 'log((1 + N) / (1 + df)) + 1',
                           'tf': '1 + log(count)', 'normalization': 'L2',
                           'tokenizer': 'NFKC + lowercase English identifiers + Chinese adjacent character bigrams; fixed stoplist',
                           'description_limit_chars': DESCRIPTION_LIMIT, 'explanation_top_terms': 8,
                           'text_fields': ['title', 'skills', 'description'],
                           'zero_similarity_ranked': False, 'clinical_or_interest_features_used': False},
            'paths': paths, 'metrics': {'elapsed_ms': elapsed,
                                       'timing_note': '单次服务器计算耗时含数据库读取，仅用于观察本次运行，不能作为模型速度优劣结论',
                                       'accuracy': None, 'labelled_relevance_count': 0},
            'notice': NOTICE,
            'limitations': ['TF-IDF 识别词面重合，无法理解同义词、语义和真实能力；中文双字片段不是词语分词。',
                            '同一模型的分数只适用于本次同一路径的冻结候选集；新增、删除或更新机会可能改变IDF和排序。',
                            '文本内容长短和写法会影响结果；城市偏好属于结构化规则，未加入文本查询。',
                            '未知资格仍需核对原文；模拟数据只验证流程，不能证明真实推荐效果。']}


@router.post('/recommendations')
def recommendation_experiment(data_kind: str = Query('public', pattern='^(demo|public)$'),
                              user=Depends(current_user), db=Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)))
    if not profile:
        raise HTTPException(422, '请先保存个人画像，再对照推荐方法')
    return compare_text_models(db, profile, data_kind)
