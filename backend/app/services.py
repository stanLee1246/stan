import csv
import hashlib
import io
from datetime import date
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select

from .models import IngestionBatch, Outcome

PATH_LABELS = {'employment': '企业就业', 'postgraduate': '升学', 'civil_service': '公务员',
               'public_institution': '事业单位', 'unresolved': '待落实', 'other': '其他', 'internship': '实习'}
CITY_ALIASES = {'长沙市': '长沙', '衡阳市': '衡阳', '广州市': '广州', '深圳市': '深圳', '武汉市': '武汉'}
SKILL_ALIASES = {'python': 'Python', 'mysql': 'MySQL', 'sql': 'SQL', 'vue': 'Vue', 'vue3': 'Vue',
                 'excel': 'Excel', 'java': 'Java', 'pandas': 'pandas', 'spark': 'Spark', 'echarts': 'ECharts'}
REQUIRED_COLUMNS = ['student_key', 'major', 'graduation_year', 'path', 'city', 'observed_on',
                    'confirmation_status', 'source_record_id', 'source_url']


def normalize_skill(value):
    return SKILL_ALIASES.get(value.strip().lower(), value.strip())


def normalize_city(value):
    return CITY_ALIASES.get(value.strip(), value.strip())


def profile_dict(profile):
    if not profile:
        return None
    result = {key: getattr(profile, key) for key in ['id', 'version', 'major', 'graduation_year', 'stage',
              'degree', 'english', 'internship_months', 'summary', 'valid_from', 'valid_to', 'recorded_at']}
    for kind in ['skills', 'cities', 'intents']:
        result[kind] = [tag.value for tag in profile.tags if tag.kind == kind]
    return result


def opportunity_dict(item):
    result = {key: getattr(item, key) for key in ['id', 'version', 'title', 'organization', 'path',
              'organization_type', 'city', 'skills', 'majors', 'minimum_degree', 'description',
              'deadline', 'published_at', 'source_url', 'data_kind', 'requirements_verified', 'fetched_at']}
    result['expired'] = item.deadline is not None and item.deadline < date.today()
    return result


def import_outcomes(db, user_id, payload):
    if payload.data_kind == 'authorized' and not payload.authorized_consent:
        raise HTTPException(422, '导入真实逐人记录前必须确认已取得授权，并使用匿名标识')
    reader = csv.DictReader(io.StringIO(payload.csv_content.lstrip('\ufeff')), strict=True)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or set(reader.fieldnames) != set(REQUIRED_COLUMNS):
        raise HTTPException(422, 'CSV 表头必须与模板完全一致，不得包含姓名、电话等额外字段')
    try:
        rows = list(reader)
    except csv.Error:
        raise HTTPException(422, 'CSV 格式损坏，请使用 UTF-8 CSV 模板')
    if not rows or len(rows) > 2000:
        raise HTTPException(422, '每批应包含 1–2000 条记录')
    batch = IngestionBatch(source_name=payload.source_name, data_kind=payload.data_kind,
                           content_hash=hashlib.sha256(payload.csv_content.encode()).hexdigest(),
                           raw_content=payload.csv_content, imported_by=user_id)
    db.add(batch)
    db.flush()
    quality = {'total': len(rows), 'accepted': 0, 'rejected': 0, 'duplicates': 0, 'errors': [],
               'cleaning_version': 'outcome-v1', 'manual_parse_accuracy': None}
    complete_cells = 0
    for line, row in enumerate(rows, start=2):
        complete_cells += sum(bool((row.get(c) or '').strip()) for c in REQUIRED_COLUMNS)
        try:
            if None in row or any(row.get(c) is None for c in REQUIRED_COLUMNS):
                raise ValueError('列数与表头不一致')
            key = row['student_key'].strip()
            if not 6 <= len(key) <= 64 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in key):
                raise ValueError('student_key 必须为 6–64 位随机匿名标识')
            major = row['major'].strip()
            if not 2 <= len(major) <= 100:
                raise ValueError('专业名称长度无效')
            year = int(row['graduation_year'])
            if not 2000 <= year <= date.today().year:
                raise ValueError('毕业届次必须在 2000 年至当前年之间')
            path = row['path'].strip()
            if path not in PATH_LABELS or path == 'internship':
                raise ValueError('实际毕业去向不能是实习或备考意向')
            observed = date.fromisoformat(row['observed_on'].strip())
            if observed > date.today() or observed.year < year:
                raise ValueError('观察日不能在未来或早于毕业届次')
            status = row['confirmation_status'].strip()
            if status not in ['self_report', 'school_confirmed', 'simulated']:
                raise ValueError('确认状态无效')
            if (payload.data_kind == 'demo') != (status == 'simulated'):
                raise ValueError('模拟数据与真实确认状态必须分开')
            url = row['source_url'].strip()
            parsed = urlsplit(url)
            if len(url) > 255 or parsed.scheme not in ['http', 'https'] or not parsed.hostname or parsed.username:
                raise ValueError('来源必须是无凭据的 HTTP/HTTPS 链接')
            record_id = row['source_record_id'].strip()
            if not 1 <= len(record_id) <= 80:
                raise ValueError('来源记录编号无效')
            city = normalize_city(row['city']) or None
            if city and len(city) > 80:
                raise ValueError('城市名称过长')
            values = dict(student_key=key, major=major, graduation_year=year, path=path, city=city,
                          observed_on=observed, confirmation_status=status, source_name=payload.source_name,
                          source_record_id=record_id, source_url=url, data_kind=payload.data_kind)
            existing = db.scalar(select(Outcome).where(Outcome.source_name == payload.source_name,
                                 Outcome.student_key == key, Outcome.observed_on == observed))
            if existing:
                if all(getattr(existing, k) == v for k, v in values.items()):
                    quality['duplicates'] += 1
                    continue
                raise ValueError('同一来源、匿名学生与观察日存在冲突，需人工核对；原记录未覆盖')
            # Flush per row makes repeated keys within the same CSV visible to the next lookup.
            db.add(Outcome(**values, batch_id=batch.id))
            db.flush()
            quality['accepted'] += 1
        except (ValueError, TypeError):
            quality['rejected'] += 1
            if len(quality['errors']) < 50:
                quality['errors'].append({'line': line, 'reason': '记录未通过字段、日期或重复冲突校验，请对照模板核对'})
    quality['completeness'] = round(complete_cells / (len(rows) * len(REQUIRED_COLUMNS)), 4)
    quality['duplicate_rate'] = round(quality['duplicates'] / len(rows), 4)
    quality['validation_pass_rate'] = round((quality['accepted'] + quality['duplicates']) / len(rows), 4)
    batch.quality = quality
    db.commit()
    return {'batch_id': batch.id, 'quality': quality}


def score_opportunity(profile, opportunity):
    """Observed features only. Score is a ranking value, never a success probability."""
    data = profile_dict(profile)
    if opportunity.path not in data['intents'] or (opportunity.deadline and opportunity.deadline < date.today()):
        return None
    if opportunity.majors and data['major'] not in opportunity.majors:
        return None
    degree_rank = {'junior_college': 0, 'bachelor': 1, 'master': 2, 'doctor': 3}
    if opportunity.minimum_degree and degree_rank[data['degree']] < degree_rank[opportunity.minimum_degree]:
        return None
    student_skills = {normalize_skill(s) for s in data['skills']}
    required_skills = {normalize_skill(s) for s in opportunity.skills}
    covered = sorted(student_skills & required_skills)
    missing = sorted(required_skills - student_skills)
    values, reasons = [], []
    # Empty self-reported skills mean unknown, not absence of every skill.
    if required_skills and student_skills:
        values.append((0.50, len(covered) / len(required_skills)))
        reasons.append(f'已自报技能覆盖 {len(covered)}/{len(required_skills)} 项')
    if opportunity.city and data['cities']:
        matched = normalize_city(opportunity.city) in data['cities']
        values.append((0.30, float(matched)))
        reasons.append('城市符合偏好' if matched else '城市不在当前偏好内')
    if opportunity.majors:
        values.append((0.20, 1.0))
        reasons.append('结构化专业名称匹配')
    # Complex examination eligibility remains manual even if structured fields match.
    needs_review = (opportunity.path not in ['employment', 'internship'] or
                    not opportunity.requirements_verified or not opportunity.deadline or
                    not opportunity.majors or not opportunity.minimum_degree)
    weight = sum(w for w, _ in values)
    score = round(sum(w * v for w, v in values) / weight * 100, 1) if len(values) >= 2 else None
    return {'opportunity': opportunity_dict(opportunity), 'opportunity_version': opportunity.version,
            'score': score, 'observed_weight': round(weight, 2), 'reasons': reasons,
            'matched_skills': covered, 'skill_gaps': missing if student_skills else [],
            'skills_unknown': not bool(student_skills), 'needs_review': needs_review,
            'qualification_note': '需核对原文完整资格条件；该分数不代表录用或上岸概率'}
