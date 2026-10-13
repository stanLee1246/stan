"""Opportunity analytics: distinct versions, explicit source scope, no private profiles."""
from collections import Counter
from datetime import date
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from .auth import current_user
from .database import get_db
from .models import Opportunity, Profile, now
from .services import PATH_LABELS, normalize_city, normalize_skill, profile_dict

router = APIRouter(prefix='/api', tags=['数据洞察与可观察画像'])


def latest_records(db, data_kind):
    seen, result = set(), []
    for item in db.scalars(select(Opportunity).where(Opportunity.data_kind == data_kind)
                          .order_by(Opportunity.version.desc(), Opportunity.id.desc())):
        key = (item.source_url, item.source_record_id)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def counts(counter, limit=None):
    items = sorted(counter.items(), key=lambda pair: (-pair[1], str(pair[0])))
    return [{'key': k, 'label': PATH_LABELS.get(k, k), 'count': n} for k, n in items[:limit]]


@router.get('/analytics')
def analytics(data_kind: str = Query('public', pattern='^(demo|public)$'), city: str | None = None,
              path: str | None = None, major: str | None = None, start_date: date | None = None,
              end_date: date | None = None, db=Depends(get_db)):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    records = [o for o in latest_records(db, data_kind)
               if (not city or normalize_city(o.city or '') == normalize_city(city))
               and (not path or o.path == path)
               and (not major or major in o.majors)
               and (not start_date or (o.published_at is not None and o.published_at >= start_date))
               and (not end_date or (o.published_at is not None and o.published_at <= end_date))]
    path_counts, city_counts, skill_counts = Counter(), Counter(), Counter()
    monthly_counts, source_counts, cell_counts, city_path_counts = Counter(), Counter(), Counter(), Counter()
    expired = unknown_deadline = unknown_published = verified = 0
    for item in records:
        city_name = normalize_city(item.city or '') or '未知'
        path_counts[item.path] += 1
        city_counts[city_name] += 1
        city_path_counts[(city_name, item.path)] += 1
        skills = set(normalize_skill(s) for s in item.skills if s.strip())
        skill_counts.update(skills)
        cell_counts.update((city_name, skill) for skill in skills)
        source_counts[urlsplit(item.source_url).hostname or '未知来源'] += 1
        if item.published_at:
            monthly_counts[item.published_at.strftime('%Y-%m')] += 1
        else:
            unknown_published += 1
        if item.deadline is None:
            unknown_deadline += 1
        elif item.deadline < date.today():
            expired += 1
        if item.requirements_verified and item.majors and item.minimum_degree and item.deadline:
            verified += 1
    top_cities = [v['key'] for v in counts(city_counts, 8)]
    top_skills = [v['key'] for v in counts(skill_counts, 12)]
    path_keys = [p for p in PATH_LABELS if p in path_counts]
    return {
        'data_kind': data_kind,
        'scope': {'city': city, 'path': path, 'major': major, 'start_date': start_date, 'end_date': end_date,
                  'version_rule': '同一来源URL及记录编号只取最新版本', 'date_basis': '公告发布日期；日期筛选排除未知发布日期',
                  'population': '当前筛选范围的机会/公告条目，包含已过期条目，不等于招聘人数或学校就业率'},
        'summary': {'opportunities': len(records), 'total_active': len(records) - expired - unknown_deadline,
                    'total_expired': expired, 'deadline_unknown': unknown_deadline,
                    'publication_unknown': unknown_published, 'unique_cities': len([c for c in city_counts if c != '未知']),
                    'total_skill_mentions': sum(skill_counts.values()), 'source_count': len(source_counts)},
        'paths': counts(path_counts), 'cities': counts(city_counts), 'skills': counts(skill_counts),
        'monthly': [{'month': month, 'count': n} for month, n in sorted(monthly_counts.items())],
        'heatmap': {'cities': top_cities, 'skills': top_skills,
                    'cells': [[si, ci, cell_counts[(c, s)]] for ci, c in enumerate(top_cities) for si, s in enumerate(top_skills)]},
        'city_path_matrix': {'cities': top_cities, 'paths': path_keys,
                             'series': [{'path': p, 'label': PATH_LABELS[p], 'data': [city_path_counts[(c, p)] for c in top_cities]} for p in path_keys]},
        'qualification': {'verified': verified, 'needs_review': len(records) - verified, 'deadline_unknown': unknown_deadline},
        'sources': [{'name': host, 'count': n} for host, n in sorted(source_counts.items())],
        'generated_at': now(),
        'notice': '模拟数据仅用于功能与交互演示，不能作为真实市场结论' if data_kind == 'demo' else '公开公告需核对原文，未发布/未知条件不补成零或承诺资格',
    }


@router.get('/profile/portrait')
def portrait(user=Depends(current_user), db=Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)))
    if not profile:
        return None
    values = profile_dict(profile)
    skills = set(values['skills'])
    groups = [('数据分析实践', {'Python', 'SQL', 'pandas', 'Excel'}),
              ('数据工程搭建', {'SQL', 'MySQL', 'Spark'}),
              ('可视化创作', {'Vue', 'ECharts'}),
              ('软件开发实践', {'Python', 'Java', 'Vue'})]
    tags = []
    for name, expected in groups:
        matched = sorted(skills & expected)
        if len(matched) >= 2:
            tags.append({'name': name, 'reason': '已自报 ' + '、'.join(matched), 'evidence': 'self_report', 'skills': matched})
    tags.sort(key=lambda t: -len(t['skills']))
    missing = [label for label, present in [('技能', bool(skills)), ('城市偏好', bool(values['cities'])),
               ('英语情况', values['english'] not in [None, 'unknown']), ('实习月数', values['internship_months'] is not None),
               ('项目经历', bool(values['summary'].strip()))] if not present]
    return {'profile_version': profile.version, 'observable_tags': tags[:3],
            'profile_completeness': {'filled': 5 - len(missing), 'total': 5, 'ratio': (5 - len(missing)) / 5, 'missing': missing},
            'intents': values['intents'], 'cities': values['cities'],
            'notice': '以上标签只总结你自报的技能组合，不等于技能认证或心理分类；职业兴趣通过自愿问卷另行了解。'}
