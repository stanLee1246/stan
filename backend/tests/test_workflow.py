import csv
import io
from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import IngestionBatch, LoginSession, now
from app.services import REQUIRED_COLUMNS
from conftest import login_as


def profile(**changes):
    return {'expected_version': 0, 'major': '数据科学与大数据技术', 'graduation_year': 2027,
            'skills': ['Python', 'SQL'], 'cities': ['长沙市'], 'intents': ['employment', 'postgraduate'], **changes}


def opportunity(**changes):
    return {'source_record_id': 'job-1', 'title': '测试数据岗位', 'organization': '测试单位',
            'path': 'employment', 'city': '长沙市', 'skills': ['Python', 'SQL', 'MySQL'],
            'majors': ['数据科学与大数据技术'], 'minimum_degree': 'bachelor',
            'description': '测试机会，不是真实招聘', 'deadline': str(date.today()+timedelta(days=10)),
            'source_url': 'https://example.com/job-1', 'requirements_verified': True, 'data_kind': 'demo', **changes}


def csv_rows(rows):
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(REQUIRED_COLUMNS); writer.writerows(rows)
    return stream.getvalue()


def outcome_row(i=0, **changes):
    data = dict(zip(REQUIRED_COLUMNS, [f'random_{i:06}', '数据科学与大数据技术', '2024', 'employment', '长沙市', '2025-09-01', 'simulated', f'row-{i}', 'https://example.com/outcomes']))
    data.update(changes)
    return [data[k] for k in REQUIRED_COLUMNS]


def do_import(client, admin, rows, **changes):
    return client.post('/api/admin/import/outcomes', headers=admin,
                       json={'source_name': 'test-source', 'data_kind': 'demo', 'csv_content': csv_rows(rows), **changes})


def test_health_and_register_role(client):
    assert client.get('/api/health').json()['status'] == 'ok'
    r = client.post('/api/auth/register', json={'username': 'new_user', 'nickname': '测试', 'password': 'TestingUser123!', 'role': 'admin'})
    assert r.status_code == 201 and r.json()['role'] == 'student'
    assert 'password_hash' not in r.json()
    assert client.post('/api/auth/register', json={'username':'new_user','nickname':'测试','password':'TestingUser123!'}).status_code == 409


def test_access_and_logout(client, student):
    assert client.get('/api/profile').status_code == 401
    assert client.get('/api/admin/batches', headers=student).status_code == 403
    assert client.post('/api/auth/logout', headers=student).status_code == 200
    assert client.get('/api/auth/me', headers=student).status_code == 401


def test_expired_token(client, student):
    with SessionLocal() as db:
        s = db.scalar(select(LoginSession)); s.expires_at = now()-timedelta(seconds=1); db.commit()
    assert client.get('/api/profile', headers=student).status_code == 401


def test_profile_versions_and_conflict(client, student):
    a = client.put('/api/profile', headers=student, json=profile()).json()
    assert a['version'] == 1 and a['cities'] == ['长沙']
    assert client.put('/api/profile', headers=student, json=profile()).status_code == 409
    b = client.put('/api/profile', headers=student, json=profile(expected_version=1, intents=['postgraduate'])).json()
    assert b['version'] == 2
    history = client.get('/api/profile/history', headers=student).json()
    assert len(history) == 2 and history[1]['valid_to'] == history[0]['valid_from']
    assert history[1]['intents'] == ['employment','postgraduate']


def test_profile_private_and_tag_normalization(client, student):
    assert client.put('/api/profile',headers=student,json=profile(skills=['python','Python','SQL'])).json()['skills'] == ['Python','SQL']
    other = login_as(client,'other_user')
    assert client.get('/api/profile',headers=other).json() is None
    assert client.get('/api/profile/history',headers=other).json() == []


def test_no_recommendation_without_profile(client, student):
    assert client.post('/api/recommendations',headers=student).status_code == 422


def test_recommendation_score_and_gap(client, student, admin):
    client.put('/api/profile',headers=student,json=profile())
    assert client.post('/api/admin/opportunities',headers=admin,json=opportunity()).status_code == 201
    run = client.post('/api/recommendations?data_kind=demo',headers=student).json()
    r = run['results'][0]
    assert r['score'] == 83.3 and r['skill_gaps'] == ['MySQL'] and not r['needs_review']
    assert r['opportunity_version'] == 1


def test_unknown_skills_do_not_mean_zero(client, student, admin):
    client.put('/api/profile',headers=student,json=profile(skills=[],cities=[]))
    client.post('/api/admin/opportunities',headers=admin,json=opportunity())
    r = client.post('/api/recommendations?data_kind=demo',headers=student).json()['results'][0]
    assert r['score'] is None and r['skills_unknown'] and r['skill_gaps'] == []


def test_filter_expiry_major_degree_and_path(client, student, admin):
    client.put('/api/profile',headers=student,json=profile())
    for i, changes in enumerate([{'deadline':str(date.today()-timedelta(days=1))}, {'majors':['护理学']}, {'minimum_degree':'master'}, {'path':'civil_service'}]):
        client.post('/api/admin/opportunities',headers=admin,json=opportunity(source_record_id=f'job-{i}', source_url=f'https://example.com/job-{i}', **changes))
    assert client.post('/api/recommendations?data_kind=demo',headers=student).json()['results'] == []


def test_exams_always_require_review(client, student, admin):
    client.put('/api/profile',headers=student,json=profile())
    client.post('/api/admin/opportunities',headers=admin,json=opportunity(path='postgraduate'))
    r=client.post('/api/recommendations?data_kind=demo',headers=student).json()['results'][0]
    assert r['needs_review']


def test_recommendation_history_is_immutable_and_private(client, student, admin):
    client.put('/api/profile',headers=student,json=profile())
    client.post('/api/admin/opportunities',headers=admin,json=opportunity())
    old = client.post('/api/recommendations?data_kind=demo',headers=student).json()
    updated = client.post('/api/admin/opportunities',headers=admin,json=opportunity(title='新版岗位',skills=['SQL'])).json()
    assert updated['version'] == 2
    client.put('/api/profile',headers=student,json=profile(expected_version=1, skills=['SQL']))
    new = client.post('/api/recommendations?data_kind=demo',headers=student).json()
    h = client.get('/api/recommendations/history',headers=student).json()
    assert new['profile_version'] == 2 and h[1]['results'] == old['results']
    assert h[1]['results'][0]['opportunity']['title'] == '测试数据岗位'
    assert len(client.get('/api/opportunities?data_kind=demo').json()) == 1
    other=login_as(client,'another_user')
    assert client.get('/api/recommendations/history',headers=other).json() == []


def test_import_idempotence_and_raw_provenance(client, admin):
    rows = [outcome_row(i) for i in range(6)]
    first = do_import(client,admin,rows).json()
    assert first['quality']['accepted'] == 6
    second = do_import(client,admin,rows).json()
    assert second['quality']['accepted'] == 0 and second['quality']['duplicates'] == 6
    d = client.get('/api/dashboard?data_kind=demo').json()
    assert d['sample_size'] == 6 and d['cities'][0]['label'] == '长沙' and d['batch_ids'] == [first['batch_id']]
    batches = client.get('/api/admin/batches',headers=admin).json()
    assert len(batches[0]['content_hash']) == 64 and 'raw_content' not in batches[0]


def test_raw_csv_larger_than_mysql_text_is_preserved(client, admin):
    rows = [outcome_row(i, major='数据科学与大数据技术' * 5) for i in range(500)]
    content = csv_rows(rows)
    assert len(content.encode()) > 65535
    result = do_import(client, admin, rows).json()
    assert result['quality']['accepted'] == 500
    with SessionLocal() as db:
        assert db.get(IngestionBatch, result['batch_id']).raw_content == content


def test_duplicates_within_file_and_conflicting_rows(client,admin):
    r=do_import(client,admin,[outcome_row(),outcome_row(),outcome_row(city='衡阳')]).json()['quality']
    assert (r['accepted'],r['duplicates'],r['rejected']) == (1,1,1)


def test_import_rejects_intents_future_dates_and_bad_types(client,admin):
    rows=[outcome_row(0,path='internship'),outcome_row(1,observed_on='2099-01-01'),outcome_row(2,graduation_year='broken'),outcome_row(3,confirmation_status='school_confirmed')]
    q=do_import(client,admin,rows).json()['quality']
    assert q['rejected'] == 4 and q['accepted'] == 0
    assert len(q['errors']) == 4 and q['manual_parse_accuracy'] is None


def test_import_requires_authorization_and_correct_header(client,admin):
    rows=[outcome_row(confirmation_status='self_report')]
    assert do_import(client,admin,rows,data_kind='authorized').status_code == 422
    r=client.post('/api/admin/import/outcomes',headers=admin,json={'source_name':'test-source','csv_content':'name,phone\n张三,123'})
    assert r.status_code == 422


def test_latest_observation_not_double_counted(client,admin):
    do_import(client,admin,[outcome_row(0),outcome_row(0,observed_on='2026-01-01',path='postgraduate')])
    d=client.get('/api/dashboard?data_kind=demo').json()
    assert d['sample_size'] == 1 and d['paths'][0]['key'] == 'postgraduate'
    past=client.get('/api/dashboard?data_kind=demo&observed_on=2025-10-01').json()
    assert past['paths'][0]['key'] == 'employment'


def test_sources_never_summed(client,admin):
    do_import(client,admin,[outcome_row(0)])
    do_import(client,admin,[outcome_row(1)],source_name='second-source')
    assert client.get('/api/dashboard?data_kind=demo').status_code == 422
    assert client.get('/api/dashboard?data_kind=demo&source_name=test-source').json()['sample_size'] == 1


def test_demo_and_real_are_separate(client,admin):
    do_import(client,admin,[outcome_row(0)])
    assert client.get('/api/dashboard').json()['sample_size'] == 0


def test_small_sample_and_complementary_suppression(client,admin):
    do_import(client,admin,[outcome_row(i,confirmation_status='self_report') for i in range(4)],data_kind='authorized',authorized_consent=True)
    d=client.get('/api/dashboard').json()
    assert d['sample_size'] is None and not d['paths'] and not d['cities']
    do_import(client,admin,[outcome_row(4,confirmation_status='self_report'),outcome_row(5,confirmation_status='self_report',path='postgraduate')],data_kind='authorized',authorized_consent=True)
    d=client.get('/api/dashboard').json()
    assert d['sample_size'] == 6 and d['paths'] == [] and 'paths' in d['suppressed_dimensions']
    assert d['cities'][0]['count'] == 6


def test_experience_consent_moderation_withdrawal(client,student,admin):
    post={'title':'毕业经验分享','body':'这是经过本人授权的经历描述，仅用于测试审核和撤回的完整流程。','graduation_year':2025,'city':'衡阳','path':'employment','public_consent':False}
    assert client.post('/api/experiences',headers=student,json=post).status_code == 422
    post['public_consent']=True
    r=client.post('/api/experiences',headers=student,json=post).json()
    assert client.get('/api/experiences').json() == []
    assert client.post(f"/api/admin/experiences/{r['id']}/moderate",headers=student,json={'status':'approved'}).status_code == 403
    assert client.post(f"/api/admin/experiences/{r['id']}/moderate",headers=admin,json={'status':'approved'}).status_code == 200
    assert len(client.get('/api/experiences').json()) == 1
    other=login_as(client,'other_user')
    assert client.delete(f"/api/experiences/{r['id']}",headers=other).status_code == 404
    assert client.delete(f"/api/experiences/{r['id']}",headers=student).status_code == 200
    assert client.get('/api/experiences').json() == []
    assert client.post(f"/api/admin/experiences/{r['id']}/moderate",headers=admin,json={'status':'approved'}).status_code == 409


def test_school_has_no_invented_statistics(client):
    assert client.get('/api/school').json()['metrics'] == []
