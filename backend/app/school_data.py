"""Import and inspect the user's school export without promoting it to verified facts."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from .database import get_db
from .school_models import SchoolDataset, UniversityMajorSnapshot, UniversitySnapshot

router = APIRouter(prefix='/api/school', tags=['school data'])
BUNDLED_DATA = Path(__file__).resolve().parents[2] / 'data' / 'school-export-20261014.json'


def _canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _percent(value):
    try:
        result = Decimal(value.removesuffix('%'))
    except (AttributeError, InvalidOperation):
        raise ValueError('Invalid source percentage') from None
    if not result.is_finite() or not 0 <= result <= 100:
        raise ValueError('Source percentages must be between 0 and 100')
    return result


def reconcile_school_data(payload):
    """Validate source fields, then retain differences instead of silently overwriting them."""
    source, universities, majors = payload['source'], payload['universities'], payload['majors']
    if payload['schema_version'] != 'school-export-v1':
        raise ValueError('Unsupported school export version')
    if len({u['name'] for u in universities}) != len(universities):
        raise ValueError('Duplicate source university')
    if len({(m['name'], m['level']) for m in majors}) != len(majors):
        raise ValueError('Duplicate source major')
    for row in universities + majors:
        for key in ('students', 'staff', 'source_order', 'founded_year'):
            if key in row and (type(row[key]) is not int or row[key] < 0):
                raise ValueError('Counts and source order must be nonnegative integers')
    for row in majors:
        _percent(row['reported_student_share'])
        _percent(row['reported_employment_rate'])
    focus = next((u for u in universities if u['name'] == source['focus_university']), None)
    if focus is None:
        raise ValueError('Focus university missing from export')
    major_students = sum(m['students'] for m in majors)
    disciplines = defaultdict(lambda: {'major_count': 0, 'students': 0})
    for major in majors:
        disciplines[major['discipline']]['major_count'] += 1
        disciplines[major['discipline']]['students'] += major['students']
    source_disciplines = {d['name']: d for d in payload['discipline_summary']}
    summaries_match = set(disciplines) == set(source_disciplines) and all(
        all(source_disciplines[name][key] == values[key] for key in ('major_count', 'students'))
        for name, values in disciplines.items()
    )
    checks = [
        {'code': 'university_count', 'passed': len(universities) == source['declared_university_count'],
         'recorded': source['declared_university_count'], 'calculated': len(universities)},
        {'code': 'major_count', 'passed': len(majors) == source['declared_major_count'],
         'recorded': source['declared_major_count'], 'calculated': len(majors)},
        {'code': 'major_student_total', 'passed': major_students == source['declared_major_students'],
         'recorded': source['declared_major_students'], 'calculated': major_students},
        {'code': 'discipline_rollup', 'passed': summaries_match},
    ]
    warnings = [{
        'code': 'unverified_source',
        'message': '资料为用户提供的本地数据库导出，尚未与学校官方报告独立核验；导出时间不等于统计年份。',
    }, {
        'code': 'employment_definition_missing',
        'message': '31项原文就业率缺少毕业届次、观察日期、统计定义及人数分母，仅保留原值供复核，不参与职业推荐或学校就业率排名。',
    }, {
        'code': 'focus_label_scope',
        'message': '原文“重点建设”标记只表示本次数据整理的重点，不代表官方重点高校认定。',
    }]
    if focus['students'] != major_students:
        warnings.append({
            'code': 'school_major_total_mismatch',
            'message': f"学校概况记录{focus['students']:,}人，31个专业明细合计{major_students:,}人，相差{major_students-focus['students']:+,}人。原文简介为约数，统计时点未给出，两项原值分别保留。",
            'school_students': focus['students'], 'major_students': major_students,
            'difference': major_students - focus['students'],
        })
    if any(not check['passed'] for check in checks):
        warnings.append({'code': 'summary_reconciliation_failed', 'message': '来源汇总与明细存在差异，请查看核对结果；未改写原始数值。'})
    declared_denominator = source['declared_major_students']
    share_errors = [m['name'] for m in majors if declared_denominator and abs(
        _percent(m['reported_student_share']) - Decimal(m['students']) * 100 / declared_denominator
    ) > Decimal('0.0051')]
    if share_errors:
        warnings.append({'code': 'reported_share_mismatch', 'message': '部分原文人数占比与所述分母不一致，保留原值供核对。', 'majors': share_errors})
    return {
        'status': 'needs_review', 'checks': checks, 'warnings': warnings,
        'university_count': len(universities), 'major_count': len(majors),
        'total_school_students': sum(u['students'] for u in universities),
        'total_school_staff': sum(u['staff'] for u in universities),
        'major_students': major_students, 'focus_school_students': focus['students'],
        'employment_metrics_eligible': False,
        'reported_percentage_sum': str(sum(_percent(m['reported_student_share']) for m in majors)),
        'discipline_summary_matches_details': summaries_match,
    }


def import_bundled_school_data(db):
    """Called after every init-db migration; no user account, demo flag or DOCX dependency."""
    payload = json.loads(BUNDLED_DATA.read_text(encoding='utf-8'))
    quality = reconcile_school_data(payload)
    source = payload['source']
    payload_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    existing = db.scalar(select(SchoolDataset).where(SchoolDataset.file_sha256 == source['file_sha256']))
    if existing:
        if existing.payload_sha256 != payload_hash:
            raise ValueError('School export changed under the same source file hash; preserve versioned provenance')
        return {'dataset_id': existing.id, 'duplicate': True, 'universities': quality['university_count'], 'majors': quality['major_count']}
    dataset = SchoolDataset(
        file_name=source['file_name'], file_sha256=source['file_sha256'], payload_sha256=payload_hash,
        schema_version=payload['schema_version'], exported_at=source['exported_at'],
        verification_status='unverified', provenance=source, raw_payload=payload, quality=quality,
    )
    db.add(dataset)
    db.flush()
    focus_id = None
    for row in payload['universities']:
        university = UniversitySnapshot(dataset_id=dataset.id, city=source['city'], **row)
        db.add(university)
        db.flush()
        if university.name == source['focus_university']:
            focus_id = university.id
    for row in payload['majors']:
        db.add(UniversityMajorSnapshot(dataset_id=dataset.id, university_id=focus_id, **row))
    db.commit()
    return {'dataset_id': dataset.id, 'duplicate': False, 'universities': len(payload['universities']), 'majors': len(payload['majors'])}


@router.get('/data')
def school_dataset(
    district: str = Query('', max_length=40), institution_type: str = Query('', max_length=40),
    university: str = Query('', max_length=120), discipline: str = Query('', max_length=40),
    level: str = Query('', max_length=20), major: str = Query('', max_length=120), db=Depends(get_db),
):
    dataset = db.scalar(select(SchoolDataset).order_by(SchoolDataset.id.desc()).limit(1))
    if dataset is None:
        raise HTTPException(status_code=404, detail='学校资料尚未导入，请重新运行本地安装脚本完成数据初始化。')
    schools = list(db.scalars(select(UniversitySnapshot).where(UniversitySnapshot.dataset_id == dataset.id).order_by(UniversitySnapshot.source_order)))
    majors = list(db.scalars(select(UniversityMajorSnapshot).where(UniversityMajorSnapshot.dataset_id == dataset.id).order_by(UniversityMajorSnapshot.source_order)))
    matching_schools = [u for u in schools if (not district or u.district == district)
                       and (not institution_type or u.institution_type == institution_type)
                       and (not university or university in u.name)]
    matching_majors = [m for m in majors if (not discipline or m.discipline == discipline)
                      and (not level or m.level == level) and (not major or major in m.name)]
    discipline_rows = defaultdict(lambda: {'major_count': 0, 'students': 0})
    for row in matching_majors:
        discipline_rows[row.discipline]['major_count'] += 1
        discipline_rows[row.discipline]['students'] += row.students
    all_major_students = sum(m.students for m in majors)
    return {
        'dataset_id': dataset.id, 'source': {**dataset.provenance, 'verification_status': dataset.verification_status,
                                          'payload_sha256': dataset.payload_sha256, 'imported_at': dataset.imported_at},
        'quality': dataset.quality,
        'summary': {
            'universities': len(schools), 'majors': len(majors), 'school_students': sum(u.students for u in schools),
            'school_staff': sum(u.staff for u in schools), 'major_students': all_major_students,
            'matching_universities': len(matching_schools), 'matching_majors': len(matching_majors),
            'matching_major_students': sum(m.students for m in matching_majors),
        },
        'scope': {'district': district, 'institution_type': institution_type, 'university': university,
                  'discipline': discipline, 'level': level, 'major': major,
                  'school_scope': '附件所列13所高校，不作为衡阳完整高校名录',
                  'major_scope': '附件所列湖南交通工程学院31个专业；高校筛选与专业筛选分别生效',
                  'employment_metrics_eligible': False},
        'filters': {'districts': sorted({u.district for u in schools}), 'institution_types': sorted({u.institution_type for u in schools}),
                    'disciplines': sorted({m.discipline for m in majors}), 'levels': sorted({m.level for m in majors})},
        'universities': [{k: getattr(u, k) for k in ('id', 'source_order', 'name', 'city', 'institution_type', 'district', 'students', 'staff', 'founded_year', 'dataset_focus', 'description')} for u in matching_schools],
        'majors': [{**{k: getattr(m, k) for k in ('id', 'source_order', 'name', 'discipline', 'level', 'students', 'reported_student_share', 'reported_employment_rate')},
                    'calculated_student_share': float((Decimal(m.students) * 100 / all_major_students).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if all_major_students else None,
                    'student_share_denominator': all_major_students, 'employment_status': 'definition_missing'} for m in matching_majors],
        'disciplines': [{'name': name, **values} for name, values in sorted(discipline_rows.items(), key=lambda item: -item[1]['students'])],
        'source_discipline_summary': dataset.raw_payload['discipline_summary'],
        'notice': '用户整理资料，尚未独立核验；在校人数、专业在读人数与毕业就业率的统计对象不同。就业率原值仅供复核，不作为择业判断依据。',
    }
