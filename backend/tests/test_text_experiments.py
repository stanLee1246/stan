"""Numerical/eligibility/privacy contracts for the read-only lexical baseline."""
from datetime import date, timedelta
import math

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.decision_models import DecisionRun
from app.models import Opportunity
from app.text_experiments import (cosine_contributions, idf_weights, tokenize, weighted_vector)
from conftest import login_as


def profile(**changes):
    return {'expected_version': 0, 'major': '数据科学与大数据技术', 'graduation_year': 2027,
            'skills': ['Python', 'SQL'], 'cities': ['长沙'], 'intents': ['employment', 'postgraduate'],
            'summary': '使用 Python 清洗数据，SQL 完成数据库分析。', **changes}


def add(client, admin, **changes):
    payload = {'source_record_id': 'text-job', 'title': 'Python SQL 数据分析', 'organization': '模拟单位',
               'path': 'employment', 'city': '长沙', 'skills': ['Python', 'SQL'],
               'majors': ['数据科学与大数据技术'], 'minimum_degree': 'bachelor',
               'description': '使用 Python 与 SQL 清洗数据并完成分析',
               'deadline': str(date.today() + timedelta(days=10)),
               'source_url': 'https://example.com/text-job', 'requirements_verified': True,
               'data_kind': 'demo', **changes}
    response = client.post('/api/admin/opportunities', headers=admin, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def experiment(client, student, kind='demo'):
    response = client.post(f'/api/experiments/recommendations?data_kind={kind}', headers=student)
    assert response.status_code == 200, response.text
    return response.json()


def rows(result):
    return [item for path in result['paths'] for item in path['comparisons']]


def test_toy_vector_exact_smooth_idf_and_cosine_math():
    documents = [{'python': 1, 'sql': 1}, {'python': 1}]
    idf = idf_weights(documents)
    rare = 1 + math.log(3 / 2)
    assert idf == {'python': 1, 'sql': rare}
    query = weighted_vector({'sql': 1}, idf)
    doc = weighted_vector(documents[0], idf)
    score, contributions = cosine_contributions(query, doc)
    assert score == pytest.approx(rare / math.sqrt(1 + rare ** 2))
    assert contributions == [('sql', score)]
    repeated = weighted_vector({'python': 4, 'sql': 1}, idf)
    assert repeated['python'] / repeated['sql'] == pytest.approx((1 + math.log(4)) / rare)


def test_tokenizer_normalizes_punctuation_chinese_and_english_without_crossing_boundaries():
    assert tokenize('ＰＹＴＨＯＮ，SQL；C++ C#') == ['python', 'sql', 'c++', 'c#']
    assert tokenize('数据清洗，数据分析') == ['数据', '据清', '清洗', '数据', '据分', '分析']
    assert tokenize('<p>Python &amp; SQL</p> THE and 工作') == ['python', 'sql']
    assert tokenize('，。…') == []


def test_cosine_zero_and_contributions_are_bounded_deterministic():
    assert idf_weights([]) == {}
    assert weighted_vector({'absent': 1}, {'sql': 1}) == {}
    assert cosine_contributions({}, {'sql': 1}) == (0, [])
    q = {'b': 1 / math.sqrt(2), 'a': 1 / math.sqrt(2)}
    score, terms = cosine_contributions(q, dict(reversed(list(q.items()))))
    assert score == pytest.approx(1)
    assert 0 <= score <= 1
    assert [term for term, value in terms] == ['a', 'b']


def test_requires_authentication_and_saved_owner_profile(client, student):
    assert client.post('/api/experiments/recommendations').status_code == 401
    assert client.post('/api/experiments/recommendations', headers=student).status_code == 422
    assert client.post('/api/experiments/recommendations?data_kind=authorized', headers=student).status_code == 422


def test_latest_versions_data_kind_isolation_path_independence_and_no_writes(client, student, admin):
    client.put('/api/profile', headers=student, json=profile())
    old = add(client, admin, title='旧标题')
    newest = add(client, admin, title='新标题 Python SQL')
    public = add(client, admin, title='公开 Python', data_kind='public', source_record_id='public-job')
    graduate = add(client, admin, path='postgraduate', source_record_id='graduate-job',
                   source_url='https://example.com/graduate-job', title='研究生 SQL 研究')
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(DecisionRun))
    result = experiment(client, student)
    assert {item['opportunity']['id'] for item in rows(result)} == {newest['id'], graduate['id']}
    assert old['id'] not in {item['opportunity']['id'] for item in rows(result)}
    assert public['id'] not in {item['opportunity']['id'] for item in rows(result)}
    assert result['scope']['latest_in_scope'] == 2
    assert result['scope']['evaluated_candidates'] == 2
    assert len(result['paths']) == 2
    assert all(path['candidate_count'] == 1 and path['comparisons'][0]['text_rank'] == 1 for path in result['paths'])
    assert all(path['comparisons'][0]['rule_rank'] == 1 for path in result['paths'])
    assert len(rows(experiment(client, student, 'public'))) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DecisionRun)) == before
    assert result['metrics']['accuracy'] is None
    assert result['parameters']['clinical_or_interest_features_used'] is False
    assert 0 <= result['metrics']['elapsed_ms']


@pytest.mark.parametrize('change', [
    {'deadline': str(date.today() - timedelta(days=1))}, {'majors': ['护理学']},
    {'minimum_degree': 'master'}, {'path': 'civil_service'},
])
def test_clearly_ineligible_items_never_enter_corpus(client, student, admin, change):
    client.put('/api/profile', headers=student, json=profile())
    add(client, admin, **change)
    result = experiment(client, student)
    assert rows(result) == []
    assert result['scope']['evaluated_candidates'] == 0
    assert result['scope']['excluded_reason_counts_inspected']


def test_major_alone_is_not_lexical_preference_and_unknown_requirements_remain_reviewable(client, student, admin):
    client.put('/api/profile', headers=student, json=profile(skills=[], summary='', cities=[]))
    add(client, admin, majors=[], minimum_degree=None, deadline=None)
    result = experiment(client, student)
    item = rows(result)[0]
    assert result['query']['evidence_present'] is False
    assert item['text_similarity'] is None and item['text_rank'] is None
    assert item['rule_score'] is None and item['rule_rank'] is None
    assert item['eligibility'] == 'needs_review'
    assert item['matched_terms'] == []


def test_no_shared_terms_has_zero_similarity_without_meaningless_rank_and_empty_corpus_valid(client, student, admin):
    client.put('/api/profile', headers=student, json=profile(skills=['Rust'], summary=''))
    empty = experiment(client, student)
    assert empty['paths'][0]['vocabulary_size'] == 0
    add(client, admin, title='Python', skills=['Python'], description='Python')
    # Query has no vocabulary terms at all: distinguish missing evidence from observed low overlap.
    result = experiment(client, student)
    assert rows(result)[0]['text_similarity'] is None
    client.put('/api/profile', headers=student, json=profile(expected_version=1, skills=['Python'], summary=''))
    add(client, admin, title='SQL', skills=['SQL'], description='SQL', source_record_id='other-text',
        source_url='https://example.com/other-text')
    result = experiment(client, student)
    item = next(row for row in rows(result) if row['opportunity']['title'] == 'SQL')
    assert item['text_similarity'] == 0 and item['text_rank'] is None


def test_contributions_reconstruct_score_and_reruns_freeze_inputs(client, student, admin):
    client.put('/api/profile', headers=student, json=profile())
    add(client, admin)
    first, again = experiment(client, student), experiment(client, student)
    one, two = rows(first)[0], rows(again)[0]
    assert one == two
    assert one['text_similarity'] == one['contribution_sum']
    assert sum(term['contribution'] for term in one['matched_terms']) + one['unshown_contribution'] == pytest.approx(one['text_similarity'], abs=1e-7)
    assert first['paths'][0]['corpus_fingerprint'] == again['paths'][0]['corpus_fingerprint']
    assert first['query']['fingerprint'] == again['query']['fingerprint']
    other = login_as(client, 'text_other')
    client.put('/api/profile', headers=other, json=profile(skills=['Java'], summary=''))
    isolated = experiment(client, other)
    assert isolated['query']['skills'] == ['Java'] and 'Python' not in isolated['query']['skills']


def test_latest_eligible_pool_cap_is_explicit_and_exclusions_do_not_consume_it(client, student):
    client.put('/api/profile', headers=student, json=profile())
    with SessionLocal() as db:
        db.add_all([Opportunity(source_record_id=f'cap-{i}', source_url=f'https://example.com/cap-{i}',
                               title='Python', organization='模拟', path='employment', city='长沙',
                               skills=['Python'], majors=['数据科学与大数据技术'], minimum_degree='bachelor',
                               description='Python', deadline=date.today() + timedelta(days=10), data_kind='demo')
                    for i in range(102)])
        db.add(Opportunity(source_record_id='excluded-newest', source_url='https://example.com/excluded-newest',
                           title='过期', organization='模拟', path='employment', city='长沙', skills=['Python'],
                           majors=[], minimum_degree=None, description='', deadline=date.today() - timedelta(days=1), data_kind='demo'))
        db.commit()
    result = experiment(client, student)
    assert len(rows(result)) == 100
    assert result['scope']['latest_in_scope'] == 103
    assert result['scope']['candidate_cap_reached'] is True
    assert result['scope']['inspected_snapshots'] == 102
    assert result['scope']['exclusion_counts_complete'] is False
