from datetime import date, timedelta

from test_workflow import opportunity, profile


def test_analytics_uses_latest_version_and_distinct_skill_mentions(client, admin):
    first = opportunity(skills=['Python', 'python', 'SQL'], published_at='2026-02-01')
    client.post('/api/admin/opportunities', headers=admin, json=first)
    client.post('/api/admin/opportunities', headers=admin, json={**first, 'city': '衡阳', 'skills': ['SQL']})
    result = client.get('/api/analytics?data_kind=demo').json()
    assert result['summary']['opportunities'] == 1
    assert result['skills'] == [{'key': 'SQL', 'label': 'SQL', 'count': 1}]
    assert result['cities'][0]['key'] == '衡阳'
    assert result['monthly'] == [{'month': '2026-02', 'count': 1}]
    assert result['heatmap']['cells'] == [[0, 0, 1]]
    assert result['city_path_matrix']['series'][0]['data'] == [1]


def test_analytics_unknown_deadline_and_filters(client, admin):
    client.post('/api/admin/opportunities', headers=admin, json=opportunity(deadline=None, published_at=None))
    client.post('/api/admin/opportunities', headers=admin, json=opportunity(source_record_id='job2', source_url='https://example.com/job2',
                 deadline=str(date.today() - timedelta(days=1)), published_at='2026-03-01', city='衡阳'))
    result = client.get('/api/analytics?data_kind=demo').json()
    assert result['summary']['total_expired'] == 1 and result['summary']['deadline_unknown'] == 1
    assert result['summary']['total_active'] == 0 and result['summary']['publication_unknown'] == 1
    assert len(client.get('/api/analytics?data_kind=demo&city=衡阳市').json()['cities']) == 1
    dated = client.get('/api/analytics?data_kind=demo&start_date=2026-01-01').json()
    assert dated['summary']['opportunities'] == 1
    assert client.get('/api/analytics?start_date=2026-04-01&end_date=2026-01-01').status_code == 422
    assert client.get('/api/analytics').json()['summary']['opportunities'] == 0


def test_portrait_observable_tags_and_privacy(client, student):
    assert client.get('/api/profile/portrait').status_code == 401
    client.put('/api/profile', headers=student, json=profile(skills=['SQL', 'MySQL', 'Python']))
    result = client.get('/api/profile/portrait', headers=student).json()
    assert {t['name'] for t in result['observable_tags']} >= {'数据工程搭建', '数据分析实践'}
    assert '英语情况' in result['profile_completeness']['missing']
    assert all(t['evidence'] == 'self_report' for t in result['observable_tags'])


def test_quality_exposes_field_denominators_without_fake_empty_percentages(client, admin):
    empty = client.get('/api/analytics').json()['quality']
    assert empty['denominator'] == 0 and all(row['coverage'] is None for row in empty['fields'])
    client.post('/api/admin/opportunities', headers=admin, json=opportunity(city=None,skills=[],majors=[],minimum_degree=None,published_at=None,deadline=None))
    client.post('/api/admin/opportunities', headers=admin, json=opportunity(source_record_id='known',source_url='https://example.com/known',published_at='2026-10-01'))
    quality = client.get('/api/analytics?data_kind=demo').json()['quality']
    assert quality['denominator'] == 2
    assert all(row['known'] == 1 and row['unknown'] == 1 and row['coverage'] == .5 for row in quality['fields'])
    assert quality['qualification_review'] == 1
    assert 'score' not in quality


def test_chart_drillthrough_filters_preserve_latest_versions_dates_and_scope(client, admin):
    base=opportunity(skills=['Python'],published_at='2026-10-01')
    client.post('/api/admin/opportunities',headers=admin,json=base)
    client.post('/api/admin/opportunities',headers=admin,json={**base,'skills':['SQL']})
    client.post('/api/admin/opportunities',headers=admin,json=opportunity(source_record_id='skill-match',source_url='https://example.com/skill-match',skills=['python','SQL'],city='衡阳市',published_at='2026-10-02'))
    client.post('/api/admin/opportunities',headers=admin,json=opportunity(source_record_id='date-unknown',source_url='https://example.com/date-unknown',skills=['Python'],city='衡阳',published_at=None))
    query='data_kind=demo&skill=PYTHON&city=衡阳市&path=employment&major=数据科学与大数据技术&start_date=2026-10-01&end_date=2026-10-31&include_expired=true'
    result=client.get('/api/opportunities?'+query)
    assert result.status_code==200 and len(result.json())==1
    assert result.json()[0]['source_url']=='https://example.com/skill-match'
    assert client.get('/api/opportunities?skill=Python&include_expired=true').json()==[]
    assert client.get('/api/opportunities?data_kind=demo&start_date=2026-11-01&end_date=2026-01-01').status_code==422
