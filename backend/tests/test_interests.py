import csv
import io

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.decision_models import DecisionRun
from app.interest_models import InterestResponse, RoleDisplay
from app.interests import CSV_REQUIRED, INSTRUMENT_VERSION, QUESTION_IDS, classify_scores, normalize_answers, score_answers
from app.models import IngestionBatch
from conftest import login_as


def profile():
    return {'expected_version': 0, 'major': '数据科学与大数据技术', 'graduation_year': 2027,
            'skills': ['Python', 'SQL'], 'cities': ['衡阳市'], 'intents': ['employment', 'postgraduate']}


def answers(primary='I', secondary='C'):
    return {key: 5 if key.startswith(primary) else 4 if secondary and key.startswith(secondary) else 2 for key in QUESTION_IDS}


def submission(**changes):
    return {'instrument_version': INSTRUMENT_VERSION, 'profile_version': 1, 'consent': True,
            'submission_id': 'stable-submit-001', 'answers': answers(), **changes}


def record(**changes):
    return {'student_key': 'random_001', 'response_id': 'survey-001', 'major': '数据科学与大数据技术',
            'graduation_year': 2027, 'skills': ['python', 'Python', 'SQL'], 'cities': ['衡阳市'],
            'intents': ['employment'], 'answers': answers(), 'consent': True, **changes}


def import_json(client, admin, rows, **changes):
    return client.post('/api/admin/import/surveys', headers=admin,
                       json={'source_name': 'test-questionnaire', 'data_kind': 'demo', 'records': rows, **changes})


def test_instrument_has_stable_questions_and_original_anthropomorphic_roles(client):
    data = client.get('/api/interests/instrument').json()
    assert data['version'] == INSTRUMENT_VERSION
    assert [q['id'] for q in data['questions']] == list(QUESTION_IDS)
    assert len(data['questions']) == 30
    assert [r['code'] for r in data['roles']] == ['R', 'I', 'A', 'S', 'E', 'C', 'U']
    assert all(r['image_url'] == '/role-assets/sheet.png' and r['sprite_code'] == r['code'] for r in data['roles'])
    assert '尚未完成' in data['notice']


def test_unknown_not_zero_and_missing_dimension_not_scored():
    data = answers()
    data['R1'], data['R2'] = None, 'unknown'
    result = score_answers(data)
    assert result['scores']['R'] is None
    assert result['coverage']['answered_items'] == 28
    assert result['status'] == 'insufficient_data'
    assert result['primary_role'] is None
    assert normalize_answers({'R1': 'unknown'})['R1'] is None
    for invalid in [0, 6, True, 2.5, '0', 'not a response']:
        with pytest.raises(ValueError):
            score_answers({'R1': invalid})


def test_minimum_coverage_four_per_dimension():
    data = {key: 5 if key.startswith('I') else 2 for key in QUESTION_IDS}
    for dimension in 'RIASEC':
        data[f'{dimension}5'] = None
    result = score_answers(data)
    assert result['coverage']['answered_items'] == 24
    assert result['coverage']['sufficient'] is True
    assert result['primary_role'] == 'I'
    assert result['scores']['I'] == 1.0


def test_role_threshold_boundaries_low_and_equal_scores():
    low = dict.fromkeys('RIASEC', 0.55)
    assert classify_scores(low)['status'] == 'exploring'
    tied = dict.fromkeys('RIASEC', 0.80)
    assert classify_scores(tied)['status'] == 'multiple_interests'
    scores = {'R': 0.9, 'I': 0.8, 'A': 0.3, 'S': 0.2, 'E': 0.1, 'C': 0.0}
    result = classify_scores(scores)
    assert result['status'] == 'highlighted_interest'
    assert result['primary_role'] == 'R' and result['secondary_role'] == 'I'
    scores.update(R=0.8, I=0.6)
    assert classify_scores(scores)['secondary_role'] == 'I'
    scores.update(R=0.81)
    assert classify_scores(scores)['secondary_role'] is None
    scores.update(R=0.60, I=0.3)
    assert classify_scores(scores)['primary_role'] == 'R'


def test_personal_measurement_requires_consent_current_profile_and_version(client, student):
    assert client.post('/api/interests/responses', headers=student, json=submission()).status_code == 422
    assert client.put('/api/profile', headers=student, json=profile()).status_code == 200
    assert client.get('/api/profile/roles', headers=student).json() is None
    assert client.post('/api/interests/responses', headers=student, json=submission(consent=False)).status_code == 422
    assert client.post('/api/interests/responses', headers=student, json=submission(profile_version=2)).status_code == 409
    assert client.post('/api/interests/responses', headers=student, json=submission(instrument_version='old-version')).status_code == 409
    first = client.post('/api/interests/responses', headers=student, json=submission())
    assert first.status_code == 201, first.text
    assert first.json()['primary_role'] == 'I'
    assert first.json()['scores']['I'] == 1
    assert first.json()['profile_version'] == 1
    assert client.post('/api/interests/responses', headers=student, json=submission()).json()['response_id'] == first.json()['response_id']
    assert client.post('/api/interests/responses', headers=student, json=submission(answers=answers('R'))).status_code == 409


def test_owner_isolation_display_override_and_withdrawal(client, student):
    client.put('/api/profile', headers=student, json=profile())
    measured = client.post('/api/interests/responses', headers=student, json=submission()).json()
    other = login_as(client, 'other_interest_user')
    assert client.get('/api/interests/history', headers=other).json() == []
    assert client.get('/api/profile/roles', headers=other).json() is None
    assert client.delete(f"/api/interests/responses/{measured['response_id']}", headers=other).status_code == 404
    changed = client.patch('/api/profile/roles/display', headers=student, json={'display_role': 'R', 'hidden': True}).json()
    assert changed['display_role'] == 'R' and changed['manual_override'] and changed['hidden']
    assert changed['scores'] == measured['scores'] and changed['primary_role'] == 'I'
    reset = client.patch('/api/profile/roles/display', headers=student, json={'display_role': None, 'hidden': False}).json()
    assert reset['display_role'] == 'I' and not reset['manual_override']
    assert client.delete(f"/api/interests/responses/{measured['response_id']}", headers=student).status_code == 200
    assert client.get('/api/interests/history', headers=student).json() == []
    assert client.get('/api/profile/roles', headers=student).json() is None
    with SessionLocal() as db:
        assert db.scalar(select(InterestResponse)) is None
        assert db.scalar(select(RoleDisplay)) is None


def test_questionnaire_ingestion_normalizes_idempotently_preserves_provenance(client, admin, student):
    first = import_json(client, admin, [record()])
    assert first.status_code == 200, first.text
    assert first.json()['quality']['accepted'] == 1
    equivalent = record(skills=['SQL', 'Python'], cities=['衡阳'], graduation_year='2027')
    second = import_json(client, admin, [equivalent]).json()
    assert second['quality']['duplicates'] == 1 and second['quality']['accepted'] == 0
    assert client.get('/api/interests/history', headers=student).json() == []
    with SessionLocal() as db:
        response = db.scalar(select(InterestResponse))
        batch = db.get(IngestionBatch, first.json()['batch_id'])
        assert response.owner_user_id is None and response.profile_id is None
        assert response.normalized_record['skills'] == ['Python', 'SQL']
        assert response.normalized_record['cities'] == ['衡阳']
        assert response.raw_record['cities'] == ['衡阳市']
        assert batch.cleaning_version == 'survey-v1'
        assert len(batch.content_hash) == 64 and len(response.answer_hash) == 64


def test_ingestion_conflicts_consent_validation_and_demo_real_isolation(client, admin, student):
    assert import_json(client, student, [record()]).status_code == 403
    assert import_json(client, admin, [record()], data_kind='authorized').status_code == 422
    result = import_json(client, admin, [record(), record(), record(answers=answers('R')),
                          record(response_id='invalid-year', graduation_year=1900),
                          record(response_id='missing-consent', consent=False),
                          record(response_id='zero-answer', answers={'R1': 0})]).json()
    q = result['quality']
    assert q['accepted'] == 1 and q['duplicates'] == 1 and q['rejected'] == 4
    assert q['total'] == q['accepted'] + q['duplicates'] + q['rejected']
    assert import_json(client, admin, [record()], data_kind='authorized', authorized_consent=True).json()['quality']['accepted'] == 1
    with SessionLocal() as db:
        rows = list(db.scalars(select(InterestResponse)))
        assert len(rows) == 2
        assert {r.data_kind for r in rows} == {'demo', 'authorized'}
        assert all(r.primary_role == 'I' for r in rows)


def test_canonical_csv_unknown_is_retained_as_missing(client, admin):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=CSV_REQUIRED)
    writer.writeheader()
    row = {**record(), **answers()}
    row['consent'] = 'true'
    row['I5'] = 'unknown'
    writer.writerow({key: row[key] for key in CSV_REQUIRED})
    response = client.post('/api/admin/import/surveys/csv', headers=admin, json={'source_name': 'canonical-csv', 'data_kind': 'demo', 'csv_content': '\ufeff' + stream.getvalue()})
    assert response.status_code == 200, response.text
    assert response.json()['quality']['accepted'] == 1
    assert response.json()['quality']['answer_completeness'] == round(29 / 30, 4)


def test_questionnaire_export_mapping_redacts_identity_and_unknown_fields(client, admin):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['序号', '专业', '毕业届次', '同意授权', '1、我喜欢配置设备', '姓名', '手机号', '提交时间'])
    writer.writerow(['1', '软件工程', '2027', '同意', '4', '测试姓名不可存储', '13800000000', '2026-10-13'])
    payload = {'source_name': '问卷星导出', 'data_kind': 'authorized', 'authorized_consent': True,
               'csv_content': stream.getvalue(), 'field_mapping': {'R1': '1、我喜欢配置设备'}, 'ignore_columns': ['提交时间']}
    result = client.post('/api/admin/import/surveys/csv', headers=admin, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['quality']['accepted'] == 1
    assert result.json()['quality']['role_statuses'] == {'insufficient_data': 1}
    again = client.post('/api/admin/import/surveys/csv', headers=admin, json=payload).json()
    assert again['quality']['duplicates'] == 1
    with SessionLocal() as db:
        row = db.scalar(select(InterestResponse))
        batch = db.get(IngestionBatch, result.json()['batch_id'])
        assert row.student_key.startswith('anon_') and row.response_key.startswith('export_')
        assert '测试姓名不可存储' not in batch.raw_content and '13800000000' not in batch.raw_content
        assert row.normalized_record['answers']['R1'] == 4
        assert row.scores['R'] is None
        assert len(batch.quality['source_file_hash']) == 64


def test_csv_mapping_errors_no_consent_no_answers_and_unhandled_columns(client, admin):
    payload = {'source_name': '腾讯问卷导出', 'csv_content': '序号,专业,未处理字段\n1,软件工程,value\n',
               'field_mapping': {'response_id': '序号'}}
    assert client.post('/api/admin/import/surveys/csv', headers=admin, json=payload).status_code == 422
    payload['csv_content'] = '序号,同意授权,姓名\n1,同意,敏感姓名\n'
    payload['field_mapping'] = {'response_id': '序号', 'R1': '姓名'}
    assert client.post('/api/admin/import/surveys/csv', headers=admin, json=payload).status_code == 422
    payload['field_mapping'] = {'response_id': '序号'}
    assert client.post('/api/admin/import/surveys/csv', headers=admin, json=payload).status_code == 422


def test_invalid_identity_json_fields_are_rejected_and_not_stored(client, admin):
    result = import_json(client, admin, [record(name='不要存储这个姓名')]).json()
    assert result['quality']['rejected'] == 1
    with SessionLocal() as db:
        batch = db.get(IngestionBatch, result['batch_id'])
        assert '不要存储这个姓名' not in batch.raw_content


def test_rejected_consent_and_invalid_values_never_enter_batch_raw(client, admin):
    declined_marker = '未同意答案不得保存'
    invalid_year_marker = '无效年份不得保存'
    invalid_major_marker = '无效专业内容不得保存' * 20
    result = import_json(client, admin, [record(),
            record(response_id='declined-record', consent=False, answers={'R1': declined_marker}),
            record(response_id='invalid-year', graduation_year=invalid_year_marker),
            record(response_id='invalid-major', major=invalid_major_marker)]).json()
    assert result['quality']['accepted'] == 1 and result['quality']['rejected'] == 3
    with SessionLocal() as db:
        batch = db.get(IngestionBatch, result['batch_id'])
        assert all(marker not in batch.raw_content for marker in [declined_marker, invalid_year_marker, invalid_major_marker])
        import json
        retained = json.loads(batch.raw_content)
        assert len(retained['records']) == 1
        assert retained['records'][0]['raw_record']['response_id'] == 'survey-001'
        assert len(retained['rejected_rows']) == 3
        assert all(set(row) == {'line', 'error_code'} for row in retained['rejected_rows'])
        assert len(batch.quality['source_file_hash']) == 64
        assert len(list(db.scalars(select(InterestResponse)))) == 1


def test_csv_raw_override_cannot_retain_rejected_answers(client, admin):
    marker = '未授权导出内容不得保存'
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=CSV_REQUIRED)
    writer.writeheader()
    row = {**record(), **answers(), 'consent': 'false', 'R1': marker}
    writer.writerow({key: row[key] for key in CSV_REQUIRED})
    result = client.post('/api/admin/import/surveys/csv', headers=admin,
               json={'source_name': 'rejected-csv', 'csv_content': stream.getvalue()}).json()
    assert result['quality']['accepted'] == 0 and result['quality']['rejected'] == 1
    with SessionLocal() as db:
        batch = db.get(IngestionBatch, result['batch_id'])
        assert marker not in batch.raw_content
        assert 'survey-001' not in batch.raw_content
        assert len(batch.quality['source_file_hash']) == 64


def test_withdrawal_removes_related_decisions_and_progress_preserves_others(client, student):
    client.put('/api/profile', headers=student, json=profile())
    unrelated = client.post('/api/decisions/compare?data_kind=demo', headers=student, json={}).json()
    measured = client.post('/api/interests/responses', headers=student, json=submission()).json()
    related = client.post('/api/decisions/compare?data_kind=demo', headers=student, json={}).json()
    assert related['interest_response_id'] == measured['response_id']
    interest_action = next(action for action in related['action_plan'] if '兴趣验证' in action['title'])
    assert client.patch(f"/api/decisions/{related['id']}/actions/{interest_action['id']}",
                        headers=student, json={'status': 'done'}).status_code == 200
    newer_measurement = client.post('/api/interests/responses', headers=student,
                         json=submission(submission_id='newer-survey', answers=answers('R'))).json()
    newer_run = client.post('/api/decisions/compare?data_kind=demo', headers=student, json={}).json()
    assert newer_run['interest_response_id'] == newer_measurement['response_id']
    other = login_as(client, 'withdraw_other_student')
    client.put('/api/profile', headers=other, json=profile())
    client.post('/api/interests/responses', headers=other, json=submission())
    other_run = client.post('/api/decisions/compare?data_kind=demo', headers=other, json={}).json()
    result = client.delete(f"/api/interests/responses/{measured['response_id']}", headers=student)
    assert result.status_code == 200, result.text
    assert result.json()['deleted_decision_runs'] == 1
    assert '行动进度' in result.json()['message']
    assert client.get(f"/api/decisions/{related['id']}", headers=student).status_code == 404
    assert client.patch(f"/api/decisions/{related['id']}/actions/{interest_action['id']}",
                        headers=student, json={'status': 'todo'}).status_code == 404
    assert client.get(f"/api/decisions/{unrelated['id']}", headers=student).status_code == 200
    assert client.get(f"/api/decisions/{newer_run['id']}", headers=student).status_code == 200
    assert client.get(f"/api/decisions/{other_run['id']}", headers=other).status_code == 200
    assert {run['id'] for run in client.get('/api/decisions/history', headers=student).json()} == {unrelated['id'], newer_run['id']}
    with SessionLocal() as db:
        assert db.get(DecisionRun, related['id']) is None
        assert db.get(DecisionRun, unrelated['id']) is not None
        assert db.get(DecisionRun, other_run['id']) is not None


def test_new_measurement_preserves_old_profile_version_and_display_setting(client, student):
    client.put('/api/profile', headers=student, json=profile())
    first = client.post('/api/interests/responses', headers=student, json=submission()).json()
    client.patch('/api/profile/roles/display', headers=student, json={'display_role': 'A', 'hidden': False})
    client.put('/api/profile', headers=student, json={**profile(), 'expected_version': 1, 'skills': ['SQL']})
    second = client.post('/api/interests/responses', headers=student,
                         json=submission(profile_version=2, submission_id='second-submit', answers=answers('R'))).json()
    assert second['profile_version'] == 2 and second['primary_role'] == 'R'
    role = client.get('/api/profile/roles', headers=student).json()
    assert role['display_role'] == 'A' and role['manual_override']
    history = client.get('/api/interests/history', headers=student).json()
    assert history[1]['response_id'] == first['response_id']
    assert history[1]['profile_version'] == 1 and history[1]['scores'] == first['scores']


def test_ingestion_limits_rows_and_bytes(client, admin):
    assert import_json(client, admin, [record()] * 1001).status_code == 422
    # Character count alone would admit this, but the UTF-8 byte count must not.
    assert import_json(client, admin, [record(major='大' * 170000)]).status_code == 413
