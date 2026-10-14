from datetime import date
import json

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Opportunity, IngestionBatch
from app.pipeline_models import OpportunitySummary, PipelineRefreshRun, SkillAssociation
from app.data_pipeline import refresh_warehouse


def seed_opportunities(kind='demo', long=False):
    a, b = ('A' * 100, 'B' * 100) if long else ('python', 'SQL')
    with SessionLocal() as db:
        for i in range(6):
            db.add(Opportunity(source_record_id=f'{kind}-{i}', source_url=f'https://example.com/{kind}/{i}',
                title=f'测试机会{i}', organization='模拟单位', path='employment', city='衡阳市',
                skills=[a, b, a] if i < 3 else [b] if i < 5 else [], majors=[], description='功能验证样本',
                data_kind=kind, version=1))
        db.commit()


def test_pipeline_auth_and_empty_public_scope(client, student, admin):
    assert client.get('/api/admin/data-pipeline').status_code == 401
    assert client.get('/api/admin/data-pipeline', headers=student).status_code == 403
    assert client.post('/api/admin/data-pipeline/refresh', headers=student).status_code == 403
    assert client.get('/api/admin/data-pipeline?data_kind=authorized', headers=admin).status_code == 422
    assert client.post('/api/admin/data-pipeline/refresh', headers=admin).status_code == 200
    data = client.get('/api/admin/data-pipeline', headers=admin).json()
    assert data['snapshot']['summary']['opportunities'] == 0 and data['rules'] == []
    assert data['snapshot']['mining']['status'] == 'insufficient_sample'


@pytest.mark.parametrize('long', [False, True])
def test_real_materialization_counts_denominators_and_idempotence(client, admin, long):
    seed_opportunities(long=long)
    first = client.post('/api/admin/data-pipeline/refresh?data_kind=demo', headers=admin)
    assert first.status_code == 200, first.text
    data = client.get('/api/admin/data-pipeline?data_kind=demo', headers=admin).json()
    assert data['snapshot']['summary']['opportunities'] == 6
    assert data['snapshot']['summary']['known_skill_records'] == 5
    assert len(data['rules']) == 2
    antecedent = 'A' * 100 if long else 'Python'
    rule = next(r for r in data['rules'] if r['antecedent'] == antecedent)
    assert (rule['pair_count'], rule['antecedent_count'], rule['population']) == (3, 3, 6)
    assert rule['support'] == .5 and rule['confidence'] == 1
    assert data['snapshot']['aggregates']['city'] == [{'key': '衡阳', 'count': 6}]
    assert len(data['snapshot']['lineage']['source_ids']) == 6
    second = client.post('/api/admin/data-pipeline/refresh?data_kind=demo', headers=admin).json()
    assert second['status'] == 'unchanged'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OpportunitySummary)) == 1
        assert db.scalar(select(func.count()).select_from(SkillAssociation)) == 2
        assert db.scalar(select(func.count()).select_from(PipelineRefreshRun)) == 2


def test_versions_refresh_staleness_and_scope_isolation(client, admin):
    seed_opportunities()
    client.post('/api/admin/data-pipeline/refresh?data_kind=demo', headers=admin)
    with SessionLocal() as db:
        db.add(Opportunity(source_record_id='demo-0', source_url='https://example.com/demo/0', title='新版本',
            organization='模拟单位', path='employment', city=None, skills=[], majors=[], description='版本替换', data_kind='demo', version=2))
        db.commit()
    before = client.get('/api/admin/data-pipeline?data_kind=demo', headers=admin).json()
    assert before['snapshot']['stale']
    assert before['layers'][1]['rows'] == 7
    client.post('/api/admin/data-pipeline/refresh?data_kind=demo', headers=admin)
    after = client.get('/api/admin/data-pipeline?data_kind=demo', headers=admin).json()
    assert after['snapshot']['summary']['opportunities'] == 6
    assert after['snapshot']['summary']['city_unknown'] == 1
    assert not after['snapshot']['stale'] and after['rules'] == []  # pair now only appears twice
    public = client.get('/api/admin/data-pipeline', headers=admin).json()
    assert public['snapshot'] is None and public['rules'] == []


def test_pipeline_never_echoes_rejected_or_private_raw_values(client, admin):
    with SessionLocal() as db:
        db.add(IngestionBatch(source_name='不能回显的身份资料', data_kind='authorized', imported_by=1,
            content_hash='f'*64, raw_content='PRIVATE-RAW-ANSWER', cleaning_version='survey-v1',
            quality={'total':1,'rejected':1,'errors':[{'line':2,'reason':'PRIVATE-REJECTED-VALUE','error_code':'unknown-secret'}]}))
        db.commit()
    response = client.get('/api/admin/data-pipeline', headers=admin)
    assert response.status_code == 200
    assert 'PRIVATE-' not in response.text and '不能回显' not in response.text
    assert response.json()['batches'][0]['errors'][0]['line'] == 2


def test_failed_refresh_rolls_back_all_materialized_changes(client, admin, monkeypatch):
    seed_opportunities()
    client.post('/api/admin/data-pipeline/refresh?data_kind=demo', headers=admin)
    with SessionLocal() as db:
        admin_id = db.scalar(select(PipelineRefreshRun.actor_id).limit(1))
        db.add(Opportunity(source_record_id='new-row', source_url='https://example.com/new', title='额外机会',
            organization='模拟单位', path='employment', city='长沙', skills=['Python'], majors=[], description='模拟',data_kind='demo'))
        db.commit()
        old_fingerprint = db.get(OpportunitySummary, 'demo').source_fingerprint
        def fail_commit():
            db.flush()
            raise RuntimeError('simulated transaction failure')
        monkeypatch.setattr(db, 'commit', fail_commit)
        with pytest.raises(RuntimeError):
            refresh_warehouse(db, admin_id, 'demo')
    with SessionLocal() as db:
        assert db.get(OpportunitySummary, 'demo').source_fingerprint == old_fingerprint
        assert db.scalar(select(func.count()).select_from(PipelineRefreshRun)) == 1
        assert db.scalar(select(func.count()).select_from(SkillAssociation)) == 2
