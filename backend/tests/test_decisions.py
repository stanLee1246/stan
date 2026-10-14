from copy import deepcopy
from datetime import date, timedelta

import pytest
from app.database import SessionLocal
from app.decision_models import DecisionRun
from app.decisions import DecisionWeights
from app.models import Opportunity
from conftest import login_as


def student_profile(**changes):
    return {'expected_version': 0, 'major': '数据科学与大数据技术', 'graduation_year': 2027,
            'skills': ['Python', 'SQL'], 'cities': ['长沙'], 'intents': ['employment', 'postgraduate'], **changes}


def opportunity_payload(**changes):
    return {'source_record_id': 'decision-job', 'title': '数据开发练习机会', 'organization': '模拟单位',
            'path': 'employment', 'city': '长沙市', 'skills': ['Python', 'SQL', 'MySQL'],
            'majors': ['数据科学与大数据技术'], 'minimum_degree': 'bachelor',
            'description': '仅用于功能测试的模拟机会', 'deadline': str(date.today() + timedelta(days=10)),
            'source_url': 'https://example.com/decision-job', 'requirements_verified': True,
            'data_kind': 'demo', **changes}


def add_opportunity(client, admin, **changes):
    response = client.post('/api/admin/opportunities', headers=admin, json=opportunity_payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def compare(client, student, **payload):
    response = client.post('/api/decisions/compare?data_kind=demo', headers=student, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_decision_requires_owner_profile_and_authentication(client, student):
    assert client.post('/api/decisions/compare', json={}).status_code == 401
    assert client.post('/api/decisions/compare', headers=student, json={}).status_code == 422


def test_weights_change_observed_score_and_are_saved(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    item = add_opportunity(client, admin)
    baseline = compare(client, student, opportunity_ids=[item['id']])
    changed = compare(client, student, opportunity_ids=[item['id']], weights={'skills': 0.1, 'city': 0.7, 'major': 0.2})
    assert baseline['comparisons'][0]['score'] == 83.3
    assert changed['comparisons'][0]['score'] == 96.7
    assert changed['weights'] == {'skills': 0.1, 'city': 0.7, 'major': 0.2}
    assert [c['key'] for c in changed['comparisons'][0]['components']] == ['skills', 'city', 'major']
    with SessionLocal() as db:
        stored = db.get(DecisionRun, changed['id'])
        assert stored.configuration['opportunity_ids'] == [item['id']]
        assert stored.profile_version == 1


def test_unknown_evidence_is_not_zero_and_zero_weight_is_inactive(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile(skills=[], cities=[]))
    item = add_opportunity(client, admin)
    result = compare(client, student, opportunity_ids=[item['id']])['comparisons'][0]
    assert result['score'] is None and result['observed_weight'] == 0.2
    assert result['skills_unknown'] and result['skill_gaps'] == []
    assert [c['value'] for c in result['components']] == [None, None, 1.0]
    client.put('/api/profile', headers=student, json=student_profile(expected_version=1))
    single = compare(client, student, weights={'skills': 1, 'city': 0, 'major': 0})['comparisons'][0]
    assert single['score'] is None and single['observed_weight'] == 1


def test_missing_requirement_reweights_only_observed_features(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    add_opportunity(client, admin, majors=[])
    result = compare(client, student)['comparisons'][0]
    assert result['score'] == 79.2 and result['observed_weight'] == 0.8
    assert result['components'][2]['value'] is None
    assert result['eligibility'] == 'needs_review'


def test_weight_validation_and_selection_validation(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    item = add_opportunity(client, admin)
    for payload in [{'weights': {'skills': 0, 'city': 0, 'major': 0}},
                    {'weights': {'skills': -1}}, {'opportunity_ids': [item['id'], item['id']]},
                    {'opportunity_ids': []}, {'opportunity_ids': [0]}, {'opportunity_ids': list(range(1, 8))}]:
        assert client.post('/api/decisions/compare?data_kind=demo', headers=student, json=payload).status_code == 422
    with pytest.raises(ValueError):
        DecisionWeights(skills=float('inf'))


@pytest.mark.parametrize('changes,reason', [
    ({'deadline': str(date.today() - timedelta(days=1))}, '截止'),
    ({'majors': ['护理学']}, '专业'),
    ({'minimum_degree': 'master'}, '学历'),
    ({'path': 'civil_service'}, '路径'),
])
def test_selected_ineligible_opportunity_explains_hard_exclusion(client, student, admin, changes, reason):
    client.put('/api/profile', headers=student, json=student_profile())
    item = add_opportunity(client, admin, **changes)
    result = compare(client, student, opportunity_ids=[item['id']])['comparisons'][0]
    assert result['eligibility'] == 'ineligible' and result['score'] is None
    assert any(reason in text for text in result['exclusion_reasons'])
    assert compare(client, student)['comparisons'] == []


def test_latest_snapshot_only_and_wrong_kind_or_unknown_ids_rejected(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    old = add_opportunity(client, admin)
    new = add_opportunity(client, admin, title='更新后的机会')
    assert new['version'] == 2
    for data_kind, item_id in [('demo', old['id']), ('demo', 999999), ('public', new['id'])]:
        response = client.post(f'/api/decisions/compare?data_kind={data_kind}', headers=student,
                               json={'opportunity_ids': [item_id]})
        assert response.status_code == 422
    result = compare(client, student)
    assert result['comparisons'][0]['opportunity']['id'] == new['id']
    assert result['comparisons'][0]['opportunity_version'] == 2


def test_paths_remain_separate_and_empty_candidates_have_actionable_work(client, student):
    client.put('/api/profile', headers=student, json=student_profile(intents=['employment', 'postgraduate', 'civil_service']))
    result = compare(client, student)
    assert result['comparisons'] == []
    assert {p['path'] for p in result['paths']} == {'employment', 'postgraduate', 'civil_service'}
    assert all(p['candidate_count'] == 0 and p['next_actions'] for p in result['paths'])
    assert all('score' not in p for p in result['paths'])
    for path in ['employment', 'postgraduate', 'civil_service']:
        actions = [a for a in result['action_plan'] if a['path'] == path]
        assert len(actions) >= 2
        assert any('14' in a['detail'] for a in actions)
    again = compare(client, student)
    assert [a['id'] for a in result['action_plan']] == [a['id'] for a in again['action_plan']]


def test_historical_evidence_is_immutable_but_action_progress_can_change(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    add_opportunity(client, admin)
    original = compare(client, student)
    action_id = original['action_plan'][0]['id']
    for status in ['doing', 'done', 'todo']:
        changed = client.patch(f'/api/decisions/{original["id"]}/actions/{action_id}',
                               headers=student, json={'status': status})
        assert changed.status_code == 200
        assert changed.json()['action_plan'][0]['status'] == status
        assert changed.json()['comparisons'] == original['comparisons']
    assert client.patch(f'/api/decisions/{original["id"]}/actions/{action_id}', headers=student,
                        json={'status': 'broken'}).status_code == 422
    assert client.patch(f'/api/decisions/{original["id"]}/actions/missing', headers=student,
                        json={'status': 'done'}).status_code == 404
    add_opportunity(client, admin, title='未来更新机会', skills=['SQL'])
    client.put('/api/profile', headers=student, json=student_profile(expected_version=1, skills=['SQL']))
    fresh = compare(client, student)
    saved = client.get(f'/api/decisions/{original["id"]}', headers=student).json()
    assert fresh['profile_version'] == 2 and saved['profile_version'] == 1
    assert saved['comparisons'] == original['comparisons']
    with SessionLocal() as db:
        stored = db.get(DecisionRun, original['id'])
        assert stored.results['action_plan'][0]['status'] == 'todo'
        assert stored.action_states[action_id]['status'] == 'todo'


def test_decision_history_and_action_endpoints_are_owner_private(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    add_opportunity(client, admin)
    original = compare(client, student)
    other = login_as(client, 'other_decision_user')
    assert client.get('/api/decisions/history', headers=other).json() == []
    assert client.get(f'/api/decisions/{original["id"]}', headers=other).status_code == 404
    assert client.patch(f'/api/decisions/{original["id"]}/actions/{original["action_plan"][0]["id"]}',
                        headers=other, json={'status': 'done'}).status_code == 404
    assert client.get('/api/decisions/history', headers=student).json()[0]['comparisons'] == original['comparisons']


def test_interest_role_adds_exploration_without_changing_scores(client, student, admin, monkeypatch):
    import app.decisions as decisions
    client.put('/api/profile', headers=student, json=student_profile())
    add_opportunity(client, admin)
    monkeypatch.setattr(decisions, 'interest_context', lambda db, uid: {'interest_response_id': None, 'role': None})
    baseline = compare(client, student)
    monkeypatch.setattr(decisions, 'interest_context', lambda db, uid: {'interest_response_id': 7, 'role': {'label': '探索小狐狸'}})
    tagged = compare(client, student)
    assert tagged['comparisons'] == baseline['comparisons'] and tagged['interest_response_id'] == 7
    assert len(tagged['action_plan']) > len(baseline['action_plan'])


def test_global_evaluation_pool_is_bounded_and_default_shortlist_is_balanced(client, student):
    client.put('/api/profile', headers=student, json=student_profile())
    with SessionLocal() as db:
        common = opportunity_payload()
        common['deadline'] = date.today() + timedelta(days=10)
        rows = []
        for index in range(105):
            data = deepcopy(common)
            data.update(source_record_id=f'bounded-{index}', source_url=f'https://example.com/bounded-{index}',
                        path='postgraduate' if index == 104 else 'employment')
            rows.append(Opportunity(**data))
        db.add_all(rows)
        db.commit()
    result = compare(client, student)
    assert result['evaluated_candidate_count'] == 100
    assert len(result['comparisons']) == 6
    assert set(c['opportunity']['path'] for c in result['comparisons']) == {'employment', 'postgraduate'}
    assert sum(p['candidate_count'] for p in result['paths']) == 100


def test_sensitivity_exposes_skill_city_tradeoff_within_frozen_shortlist(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    skill_match = add_opportunity(client, admin, source_record_id='skill-choice',
                                  source_url='https://example.com/skill-choice', city='广州', skills=['Python', 'SQL'])
    city_match = add_opportunity(client, admin, source_record_id='city-choice',
                                 source_url='https://example.com/city-choice', skills=['Python', 'Java'])
    # This stronger candidate stays outside the explicit two-item shortlist.
    add_opportunity(client, admin, source_record_id='outside-shortlist',
                    source_url='https://example.com/outside-shortlist', skills=['Python', 'SQL'])
    result = compare(client, student, opportunity_ids=[skill_match['id'], city_match['id']])
    sensitivity = result['sensitivity']
    assert sensitivity['scope'] == 'displayed_comparisons_within_path'
    path = sensitivity['paths'][0]
    assert path['path'] == 'employment' and path['compared_count'] == 2
    by_id = {item['opportunity_id']: item for item in path['stability']}
    assert by_id[skill_match['id']]['ranks'] == {'current': 2, 'balanced': 2, 'skills_first': 1, 'city_first': 2}
    assert by_id[city_match['id']]['ranks'] == {'current': 1, 'balanced': 1, 'skills_first': 2, 'city_first': 1}
    assert all(item['status'] == 'sensitive' and item['rank_changed'] is True for item in by_id.values())
    for scenario in path['scenario_results']:
        assert {entry['opportunity_id'] for entry in scenario['rankings']} == set(by_id)
    assert result['decision_context']['selected_paths'] == ['employment', 'postgraduate']
    assert result['decision_context']['questionnaire_optional']
    assert result['decision_context']['missing_fields'] == []
    assert any('第 14 天：回看证据' in action['title'] for action in result['action_plan'])


def test_sensitivity_equal_scores_tie_and_never_rank_different_paths_together(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    first = add_opportunity(client, admin)
    second = add_opportunity(client, admin, source_record_id='tie-second', source_url='https://example.com/tie-second')
    third = add_opportunity(client, admin, source_record_id='different-path',
                            source_url='https://example.com/different-path', path='postgraduate')
    result = compare(client, student, opportunity_ids=[first['id'], second['id'], third['id']])
    by_path = {path['path']: path for path in result['sensitivity']['paths']}
    employment = by_path['employment']['stability']
    assert all(set(item['ranks'].values()) == {1} and item['status'] == 'stable' for item in employment)
    single = by_path['postgraduate']['stability'][0]
    assert single['status'] == 'insufficient_peers' and single['rank_changed'] is None


def test_sensitivity_preserves_unknowns_and_hard_exclusions(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile(skills=[], cities=[]))
    unknown = add_opportunity(client, admin)
    excluded = add_opportunity(client, admin, source_record_id='expired-choice',
                               source_url='https://example.com/expired-choice',
                               deadline=str(date.today() - timedelta(days=1)))
    result = compare(client, student, opportunity_ids=[unknown['id'], excluded['id']])
    path = result['sensitivity']['paths'][0]
    by_id = {item['opportunity_id']: item for item in path['stability']}
    assert by_id[unknown['id']]['status'] == 'insufficient_evidence'
    assert by_id[unknown['id']]['missing_dimensions'] == ['技能覆盖', '城市偏好']
    assert by_id[excluded['id']]['status'] == 'excluded'
    assert all(entry['score'] is None and entry['rank'] is None
               for scenario in path['scenario_results'] for entry in scenario['rankings'])
    assert result['decision_context']['missing_fields'] == ['自报技能', '城市偏好']


def test_sensitivity_is_immutable_and_reports_different_evidence_coverage(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    first = add_opportunity(client, admin)
    second = add_opportunity(client, admin, source_record_id='no-major', source_url='https://example.com/no-major', majors=[])
    result = compare(client, student, opportunity_ids=[first['id'], second['id']])
    assert result['sensitivity']['paths'][0]['different_evidence_coverage']
    missing = result['sensitivity']['paths'][0]['stability'][1]
    assert missing['missing_dimensions'] == ['专业条件']
    add_opportunity(client, admin, skills=['Java'], city='广州')
    client.put('/api/profile', headers=student, json=student_profile(expected_version=1, cities=['广州']))
    action_id = result['action_plan'][0]['id']
    saved = client.patch(f'/api/decisions/{result["id"]}/actions/{action_id}',
                         headers=student, json={'status': 'done'}).json()
    assert saved['sensitivity'] == result['sensitivity']
    assert saved['decision_context'] == result['decision_context']
    assert saved['decision_context']['profile_summary']['cities'] == ['长沙']


def test_sensitivity_does_not_claim_stability_if_current_weights_only_activate_one_factor(client, student, admin):
    client.put('/api/profile', headers=student, json=student_profile())
    add_opportunity(client, admin)
    add_opportunity(client, admin, source_record_id='single-weight-peer', source_url='https://example.com/single-weight-peer')
    result = compare(client, student, weights={'skills': 1, 'city': 0, 'major': 0})
    for entry in result['sensitivity']['paths'][0]['stability']:
        assert entry['ranks']['current'] is None
        assert entry['ranks']['balanced'] == 1
        assert entry['status'] == 'insufficient_evidence' and entry['rank_changed'] is None
