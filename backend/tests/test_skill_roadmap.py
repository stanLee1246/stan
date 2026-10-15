from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Opportunity
from conftest import login_as


def save_profile(client, headers, **changes):
    data = {'expected_version': 0, 'major': '数据科学与大数据技术', 'graduation_year': 2027,
            'degree': 'bachelor', 'skills': ['Python'], 'cities': ['长沙市'], 'intents': ['employment']}
    response = client.put('/api/profile', headers=headers, json={**data, **changes})
    assert response.status_code == 200, response.text


def add_record(key, **changes):
    values = {'source_record_id': key, 'version': 1, 'title': f'{key}数据实践机会', 'organization': '功能测试单位',
              'path': 'employment', 'city': '长沙市', 'skills': ['SQL'], 'majors': ['数据科学与大数据技术'],
              'minimum_degree': 'bachelor', 'description': '仅供测试的结构化样例',
              'deadline': date.today() + timedelta(days=7), 'source_url': f'https://example.com/{key}',
              'data_kind': 'demo', 'requirements_verified': True, **changes}
    with SessionLocal() as db:
        item = Opportunity(**values)
        db.add(item)
        db.commit()
        return item.id


def read_roadmap(client, headers, query='data_kind=demo'):
    response = client.get(f'/api/skills/roadmap?{query}', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_roadmap_requires_authentication_and_own_profile(client, student):
    assert client.get('/api/skills/roadmap').status_code == 401
    assert client.get('/api/skills/roadmap', headers=student).status_code == 422
    save_profile(client, student)
    assert client.get('/api/skills/roadmap?data_kind=authorized', headers=student).status_code == 422
    assert read_roadmap(client, student)['profile_state']['version'] == 1


def test_roadmap_uses_latest_records_and_explains_known_hard_exclusions(client, student):
    save_profile(client, student)
    old = add_record('versioned', skills=['OldSkill'])
    fresh = add_record('versioned', version=2, skills=['SQL', 'MySQL'])
    for key, changes in [('expired', {'deadline': date.today() - timedelta(days=1)}),
                         ('major', {'majors': ['护理学']}), ('degree', {'minimum_degree': 'master'}),
                         ('path', {'path': 'civil_service'})]:
        add_record(key, skills=['ExcludedSkill'], **changes)
    result = read_roadmap(client, student)
    assert result['summary']['all_latest_records'] == 5
    assert result['summary']['qualifying_records'] == 1
    assert result['summary']['exclusion_reasons'] == {'expired': 1, 'major': 1, 'degree': 1, 'intent': 1}
    assert {item['skill'] for item in result['skills']} == {'SQL', 'MySQL'}
    assert all([record['id'] for record in item['evidence']] == [fresh] for item in result['skills'])
    assert all(old not in [record['id'] for record in item['evidence']] for item in result['skills'])


def test_roadmap_counts_normalized_distinct_skills_per_record_and_known_denominator(client, student):
    save_profile(client, student)
    add_record('first', skills=['sql', 'SQL', ' python ', '', 'SQL'])
    add_record('second', skills=['SQL'])
    add_record('unknown', skills=[], deadline=None, majors=[], minimum_degree=None, requirements_verified=False)
    result = read_roadmap(client, student)
    assert result['summary']['qualifying_records'] == 3
    assert result['summary']['known_skill_records'] == 2
    assert result['summary']['skill_requirements_unknown'] == 1
    assert result['summary']['deadline_unknown'] == 1
    assert result['summary']['needs_review'] == 1
    sql, python = result['skills']
    assert (sql['skill'], sql['count'], sql['share'], sql['state']) == ('SQL', 2, 1, 'not_reported')
    assert (python['skill'], python['count'], python['share'], python['state']) == ('Python', 1, .5, 'self_reported')
    assert sql['known_skill_denominator'] == 2


def test_roadmap_city_preference_is_optional_and_normalized(client, student):
    save_profile(client, student, cities=['长沙市'])
    included = add_record('changsha', city='长沙')
    add_record('guangzhou', city='广州')
    add_record('unknown-city', city=None)
    assert read_roadmap(client, student)['summary']['qualifying_records'] == 3
    result = read_roadmap(client, student, 'data_kind=demo&preferred_city_only=true')
    assert result['summary']['qualifying_records'] == 1
    assert result['summary']['exclusion_reasons']['city'] == 2
    assert result['skills'][0]['evidence'][0]['id'] == included
    assert result['profile_state']['cities'] == ['长沙']
    save_profile(client, student, expected_version=1, cities=[])
    assert client.get('/api/skills/roadmap?preferred_city_only=true', headers=student).status_code == 422


def test_roadmap_unfilled_skill_inventory_never_fabricates_a_gap_or_ability_score(client, student):
    save_profile(client, student, skills=[])
    add_record('unknown-student', skills=['SQL', 'Python'])
    result = read_roadmap(client, student)
    assert result['profile_state']['skills_unknown'] is True
    assert all(item['state'] == 'unknown' for item in result['skills'])
    assert all('score' not in item and 'ability' not in item for item in result['skills'])
    assert len(result['schedule']) == 4
    assert all(item['recipe']['artifact'] and item['recipe']['verification'] for item in result['skills'])


def test_roadmap_only_uses_owner_profile_and_keeps_public_demo_separate(client, student):
    save_profile(client, student, skills=['Python'])
    other = login_as(client, 'roadmap_other')
    save_profile(client, other, skills=['SQL'], intents=['postgraduate'])
    add_record('private-demo', skills=['Python', 'SQL'])
    public_id = add_record('public', data_kind='public', skills=['pandas'])
    owner = read_roadmap(client, student)
    assert {row['state'] for row in owner['skills']} == {'self_reported', 'not_reported'}
    assert read_roadmap(client, other)['skills'] == []
    result = read_roadmap(client, student, 'data_kind=public')
    assert [item['skill'] for item in result['skills']] == ['pandas']
    assert result['skills'][0]['evidence'][0]['id'] == public_id
    assert 'roadmap_other' not in str(result) and 'user_id' not in str(result)


def test_roadmap_public_empty_stays_empty_and_unknown_skill_has_no_invented_course(client, student):
    save_profile(client, student)
    add_record('unknown-term', skills=['某领域术语'])
    public = read_roadmap(client, student, 'data_kind=public')
    assert public['summary']['all_latest_records'] == 0
    assert public['skills'] == []
    generic = read_roadmap(client, student)['skills'][0]['recipe']
    assert generic['resources'] == []
    assert '核对' in generic['practice'] and '老师' in generic['verification']


def test_roadmap_priorities_are_transparent_bounded_and_evidence_truncation_is_explicit(client, student):
    save_profile(client, student, skills=['Python'])
    for index in range(14):
        add_record(f'many-{index}', skills=['Python', 'SQL', 'pandas', 'MySQL', 'Java', 'Spark', 'Vue', 'Excel'])
    result = read_roadmap(client, student)
    assert result['summary']['distinct_skills'] == 8
    assert result['summary']['displayed_skills'] == 6
    assert len(result['skills']) == 6
    assert 'Python' not in [item['skill'] for item in result['skills']]
    for item in result['skills']:
        assert item['evidence_total'] == 14 and len(item['evidence']) == 12
        assert item['evidence_truncated'] is True
        assert item['recipe']['resources'][0]['url'].startswith('https://')
