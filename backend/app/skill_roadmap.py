"""Private, explainable learning priorities from the owner's current opportunity scope.

Frequency describes this selected set of announcements; it is not a labour-market
estimate, a measure of ability, or an outcome probability. No new personal facts
are persisted by this read-only view.
"""
from collections import Counter, defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from .auth import current_user
from .database import get_db
from .decisions import DEGREES, latest_statement
from .models import Profile, now
from .services import PATH_LABELS, normalize_city, normalize_skill, profile_dict

router = APIRouter(prefix='/api/skills', tags=['我的技能成长路线'])
RULE_VERSION = 'observed-skill-roadmap-v1'
EVIDENCE_LIMIT = 12

# Stable publisher documentation entry points, not an automatically assessed course.
RECIPES = {
    'Python': ('Python 官方教程', 'https://docs.python.org/zh-cn/3/tutorial/',
               '用 Python 读取一份公开 CSV，处理空值和重复行并输出统计摘要。',
               '一份可重复运行的脚本、输入样例与 README。',
               '保留原始行数、去重行数和异常行报告；同一输入再次运行应得到相同结果。'),
    'SQL': ('MySQL 官方 SQL 查询入门', 'https://dev.mysql.com/doc/refman/8.4/en/tutorial.html',
            '用项目本地 MySQL 建立两张练习表，完成筛选、关联、分组与聚合查询。',
            'SQL 文件、样例表与一张口径说明表。',
            '手工核对一个小样本的聚合结果，说明 JOIN 后重复计数的处理；SQL 文件须在项目本地 MySQL 中验证。'),
    'MySQL': ('MySQL 官方教程', 'https://dev.mysql.com/doc/refman/8.4/en/tutorial.html',
              '为一组非个人敏感的机会记录建表，设置唯一键并比较一条查询加索引前后的执行计划。',
              '建表与导入脚本、EXPLAIN 输出和查询口径说明。',
              '验证唯一键能拦截重复记录；固定数据和查询比较执行计划，不把小样本耗时当作通用性能结论。'),
    'pandas': ('pandas 官方入门教程', 'https://pandas.pydata.org/docs/getting_started/intro_tutorials/',
               '读取一份公开表格，规范列名与城市别名，并输出缺失率和分组统计。',
               'Notebook 或脚本、清洗前后样例与字段字典。',
               '核对原始、有效、重复和拒绝记录数能对上；未知值保留为空并说明统计分母。'),
    'Spark': ('Apache Spark 官方文档', 'https://spark.apache.org/docs/latest/',
              '用本地模式读取公开 CSV，完成一次过滤、去重和分组聚合。',
              '本地运行脚本、版本记录与同口径 SQL 对照结果。',
              '先在小样本比较 Spark 与 SQL 的行数和聚合值；本地小样本不用于声称分布式加速。'),
    'ECharts': ('Apache ECharts 官方手册', 'https://echarts.apache.org/handbook/zh/get-started/',
                '用一组有明确来源与分母的数据制作柱状图和折线图，补齐图表标题、单位和空状态。',
                '可运行图表页、数据表和指标口径说明。',
                '图表值与原始表逐项核对；检查手机宽度、键盘操作和未知值呈现。'),
    'Vue': ('Vue 官方教程', 'https://cn.vuejs.org/tutorial/',
            '用 Vue 制作一个带筛选、加载、错误和空状态的数据列表。',
            '页面代码、运行说明与交互检查清单。',
            '快速切换筛选时不显示旧响应；用键盘操作表单并在手机宽度检查布局。'),
    'Excel': ('Microsoft Excel 官方帮助', 'https://support.microsoft.com/excel',
              '将一份公开表格整理为字段一致的数据表，使用数据透视表核对分类数量。',
              '脱敏练习工作簿、清洗记录与一页结果说明。',
              '核对重复值、空值和日期类型；对一个分组进行手工复算，避免把空值计为零。'),
    'Java': ('Java 官方学习资源', 'https://dev.java/learn/',
             '编写一个读取公开 CSV 并校验字段、输出分类计数的小程序。',
             '可运行代码、示例输入、异常行报告与 README。',
             '正常、空值和重复样例都能得到可解释的输出；保留运行版本与复现命令。'),
}


def learning_recipe(skill):
    if skill in RECIPES:
        publisher, url, practice, artifact, verify = RECIPES[skill]
        resources = [{'title': publisher, 'url': url, 'kind': 'publisher_documentation'}]
    else:
        practice = f'先核对来源中“{skill}”的具体含义，选择一个与课程或目标机会相关、两周内可尝试的小任务。'
        artifact = '一页任务说明、过程记录、成果文件与引用来源。'
        verify = '请授课老师或有相关经验的同学核对任务范围和成果；记录反馈与待改进项。'
        resources = []
    return {'practice': practice, 'artifact': artifact, 'verification': verify,
            'resources': resources, 'resource_note': '官方文档用于查阅，版本和语法以你的本地工具为准；完成练习不等于获得能力认证。'}


def exclusion_reasons(data, item):
    reasons = []
    if item.path not in data['intents']:
        reasons.append('intent')
    if item.deadline and item.deadline < date.today():
        reasons.append('expired')
    if item.majors and data['major'] not in item.majors:
        reasons.append('major')
    # Only compare degrees when both structured values are known.
    if item.minimum_degree in DEGREES and data['degree'] in DEGREES and DEGREES[data['degree']] < DEGREES[item.minimum_degree]:
        reasons.append('degree')
    return reasons


@router.get('/roadmap')
def roadmap(data_kind: str = Query('public', pattern='^(demo|public)$'),
            preferred_city_only: bool = False, user=Depends(current_user), db=Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)))
    if not profile:
        raise HTTPException(422, '请先保存个人画像，再查看技能成长路线')
    data = profile_dict(profile)
    owned_skills = {normalize_skill(value) for value in data['skills'] if value.strip()}
    preferred_cities = {normalize_city(value) for value in data['cities'] if value.strip()}
    if preferred_city_only and not preferred_cities:
        raise HTTPException(422, '请先在画像中填写城市偏好，或关闭城市筛选')
    excluded = Counter()
    records, all_latest_count = [], 0
    for item in db.scalars(latest_statement(data_kind).order_by('id')):
        all_latest_count += 1
        reasons = exclusion_reasons(data, item)
        if preferred_city_only and (not item.city or normalize_city(item.city) not in preferred_cities):
            reasons.append('city')
        if reasons:
            excluded.update(reasons)
        else:
            records.append(item)
    mentions, evidence = Counter(), defaultdict(list)
    known_skill_records = unknown_deadline = needs_review = 0
    for item in records:
        required = {normalize_skill(value) for value in (item.skills or []) if isinstance(value, str) and value.strip()}
        known_skill_records += bool(required)
        unknown_deadline += item.deadline is None
        review = (not item.requirements_verified or not item.deadline or not item.majors or
                  item.minimum_degree not in DEGREES or item.path not in ['employment', 'internship'])
        needs_review += review
        mentions.update(required)
        for skill in required:
            if len(evidence[skill]) < EVIDENCE_LIMIT:
                evidence[skill].append({'id': item.id, 'version': item.version, 'title': item.title,
                                        'path': item.path, 'city': normalize_city(item.city or '') or None,
                                        'source_url': item.source_url, 'deadline': item.deadline,
                                        'needs_review': review})
    # Self-report is not a complete ability inventory. Missing tags mean unreported,
    # and a wholly empty inventory means we cannot infer any individual skill gap.
    def skill_state(skill):
        return 'unknown' if not owned_skills else 'self_reported' if skill in owned_skills else 'not_reported'
    ranked = sorted(mentions, key=lambda skill: (skill_state(skill) == 'self_reported', -mentions[skill], skill))
    skill_rows = [{'skill': skill, 'state': skill_state(skill), 'count': mentions[skill],
                   'known_skill_denominator': known_skill_records,
                   'share': round(mentions[skill] / known_skill_records, 4),
                   'evidence': evidence[skill], 'evidence_total': mentions[skill],
                   'evidence_truncated': mentions[skill] > len(evidence[skill]),
                   'recipe': learning_recipe(skill)} for skill in ranked[:6]]
    return {
        'data_kind': data_kind, 'rule_version': RULE_VERSION, 'generated_at': now(),
        'profile_state': {'version': profile.version, 'major': data['major'], 'degree': data['degree'],
                          'intents': [{'key': key, 'label': PATH_LABELS.get(key, key)} for key in data['intents']],
                          'cities': sorted(preferred_cities), 'skills_unknown': not bool(owned_skills),
                          'self_reported_skills': sorted(owned_skills)},
        'scope': {'preferred_city_only': preferred_city_only, 'as_of': date.today(),
                  'population': '当前画像意向下、没有已知专业/学历不符且未明确过期的最新机会/公告条目；条件缺失者保留并提示核对。',
                  'version_rule': '同一数据类型、来源URL和记录编号只取最新版本。',
                  'counting_rule': '每条机会内技能规范化去重；占比=提及该技能的条目数÷已列出至少一项技能的合格条目数。',
                  'priority_rule': '已填写技能时，优先展示尚未自报的技能；同组按提及条目数降序，再按名称排序，最多6项。尚未填写技能时只按频次提供探索线索。',
                  'exclusion_note': '各排除原因可重叠，不应相加作为排除条目总数；城市默认只是偏好，勾选后才筛选。'},
        'summary': {'all_latest_records': all_latest_count, 'qualifying_records': len(records),
                    'excluded_records': all_latest_count - len(records), 'exclusion_reasons': dict(excluded),
                    'known_skill_records': known_skill_records, 'skill_requirements_unknown': len(records) - known_skill_records,
                    'deadline_unknown': unknown_deadline, 'needs_review': needs_review,
                    'distinct_skills': len(mentions), 'displayed_skills': len(skill_rows)},
        'skills': skill_rows,
        'schedule': [
            {'days': '第1–3天', 'title': '核对依据，缩小任务', 'detail': '从上方选择1–3项，自行确认兴趣与时间。阅读对应机会原文和学习资料，为每项写下一个可展示成果。'},
            {'days': '第4–7天', 'title': '先完成最小练习', 'detail': '按练习建议完成一个小样例，记录输入、输出、环境与遇到的问题；课业繁忙时可只选择1项。'},
            {'days': '第8–13天', 'title': '应用到一个项目成果', 'detail': '将练习用于课程或毕业设计的小功能，保存脚本、图表或说明，请老师或同学核对一次。'},
            {'days': '第14天', 'title': '复盘，再更新画像', 'detail': '对照验证方法检查成果，记录仍未知的部分；把能举证的变化填写到画像，再回到机会与决策比较。'},
        ],
        'notice': ('当前为模拟机会，只验证学习路线流程，频次不能作为真实市场结论。' if data_kind == 'demo' else
                   '技能频次只描述当前已采集且符合本次口径的公告，不代表完整就业市场。') +
                  ' 自报不等于技能认证，未填写不等于不会；这份两周尝试计划不承诺学会、录用或报名资格。',
    }
