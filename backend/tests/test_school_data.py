import hashlib
import json
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.school_data import BUNDLED_DATA, import_bundled_school_data, reconcile_school_data
from app.school_models import SchoolDataset, UniversitySnapshot, UniversityMajorSnapshot


def seed():
    with SessionLocal() as db:
        return import_bundled_school_data(db)


def test_school_import_exact_counts_and_idempotent_provenance(client):
    first = seed()
    again = seed()
    assert not first['duplicate'] and again['duplicate']
    assert first['dataset_id'] == again['dataset_id']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SchoolDataset)) == 1
        assert db.scalar(select(func.count()).select_from(UniversitySnapshot)) == 13
        assert db.scalar(select(func.count()).select_from(UniversityMajorSnapshot)) == 31
    data = client.get('/api/school/data').json()
    assert data['summary'] == {'universities': 13, 'majors': 31, 'school_students': 175100,
        'school_staff': 12450, 'major_students': 12440, 'matching_universities': 13,
        'matching_majors': 31, 'matching_major_students': 12440}
    assert data['source']['exported_at'] == '2026-10-14 11:44:01'
    assert data['source']['verification_status'] == 'unverified'
    assert len(data['source']['file_sha256']) == 64
    assert not data['scope']['employment_metrics_eligible']
    assert all(m['student_share_denominator'] == 12440 for m in data['majors'])
    assert next(m for m in data['majors'] if m['name'] == '数据科学与大数据技术')['reported_employment_rate'] == '93.60%'


def test_school_reconciliation_keeps_scale_difference_and_raw_values(client):
    seed()
    data = client.get('/api/school/data').json()
    focus = next(u for u in data['universities'] if u['name'] == '湖南交通工程学院')
    assert focus['students'] == 12000 and sum(m['students'] for m in data['majors']) == 12440
    assert all(c['passed'] for c in data['quality']['checks'])
    warnings = json.dumps(data['quality']['warnings'], ensure_ascii=False)
    assert '440' in warnings
    assert sum(d['students'] for d in data['disciplines']) == 12440
    assert sum(d['major_count'] for d in data['disciplines']) == 31
    assert client.get('/api/school').json()['metrics'] == []


def test_school_filters_have_separate_scopes_and_major_dictionary(client):
    seed()
    data = client.get('/api/school/data?district=蒸湘区&level=本科&discipline=工学').json()
    assert all(u['district'] == '蒸湘区' for u in data['universities'])
    assert all(m['level'] == '本科' and m['discipline'] == '工学' for m in data['majors'])
    assert data['summary']['major_students'] == 12440
    assert len(client.get('/api/dictionaries').json()['majors']) == 31
    empty = client.get('/api/school/data?university=不存在高校&major=不存在专业').json()
    assert empty['universities'] == [] and empty['majors'] == []


def test_school_missing_data_explains_setup(client):
    assert client.get('/api/school/data').status_code == 404


def test_school_validator_detects_rollup_inconsistency_and_rejects_bad_values():
    payload = json.loads(BUNDLED_DATA.read_text(encoding='utf-8'))
    changed = deepcopy(payload)
    changed['majors'][0]['students'] += 1
    quality = reconcile_school_data(changed)
    assert not all(c['passed'] for c in quality['checks'])
    changed['majors'][0]['reported_employment_rate'] = 'NaN%'
    with pytest.raises(ValueError):
        reconcile_school_data(changed)
