"""Deterministic, visibly synthetic opportunity scenarios for chart and decision demos."""
from datetime import date, timedelta

from sqlalchemy import select

from .models import Opportunity


def months_before(day, count):
    index = day.year * 12 + day.month - 1 - count
    return date(index // 12, index % 12 + 1, 12)


def seed_extended_opportunities(db):
    cities = ['衡阳', '长沙', '广州', '深圳', '武汉']
    scenarios = [
        ('employment', '业务数据分析', ['Python', 'SQL', 'Excel']),
        ('employment', '数据可视化开发', ['Vue', 'ECharts', 'SQL']),
        ('employment', '数据工程实践', ['Python', 'MySQL', 'Spark']),
        ('employment', '软件应用开发', ['Java', 'SQL']),
        ('internship', '校园数据助理实习', ['Excel', 'SQL']),
        ('internship', '网站开发实习', ['Vue', 'Java']),
        ('postgraduate', '数据科学项目探索', ['Python', 'SQL']),
        ('postgraduate', '软件工程项目探索', ['Java', 'Python']),
        ('civil_service', '统计业务职位探索', ['Excel']),
        ('public_institution', '信息服务岗位探索', ['SQL', 'Python']),
    ]
    accepted = 0
    for i in range(20):
        record_id = f'enhanced-demo-{i:02}'
        if db.scalar(select(Opportunity.id).where(Opportunity.source_record_id == record_id,
                                                Opportunity.data_kind == 'demo')):
            continue
        path, title, skills = scenarios[i % len(scenarios)]
        deadline = None if i % 7 == 0 else date.today() + timedelta(days=-15 if i % 8 == 0 else 15 + i * 2)
        db.add(Opportunity(source_record_id=record_id, title=title + '（模拟）', organization=f'虚构演示单位{i + 1:02}',
                           path=path, city=cities[i % 5], skills=skills,
                           majors=['数据科学与大数据技术', '软件工程'], minimum_degree='bachelor',
                           description='合成的职业探索案例，用于数据图表、不同权重的机会比较和行动清单演示；不是可报名的真实职位。',
                           published_at=months_before(date.today(), i % 6), deadline=deadline,
                           source_url=f'https://example.com/extended-demo/{i}', data_kind='demo',
                           requirements_verified=False))
        accepted += 1
    db.commit()
    return accepted
