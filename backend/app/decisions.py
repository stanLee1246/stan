"""Explainable, versioned career decision support; scores are not probabilities."""

from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import aliased

from .auth import current_user
from .database import get_db
from .decision_models import DecisionRun
from .models import Opportunity, Profile
from .services import PATH_LABELS, normalize_city, normalize_skill, opportunity_dict, profile_dict


router = APIRouter(prefix='/api/decisions', tags=['辅助决策'])
MODEL_VERSION = 'observed-decision-v1'
POOL_LIMIT = 100
COMPARISON_LIMIT = 6
DEGREES = {'junior_college': 0, 'bachelor': 1, 'master': 2, 'doctor': 3}
NOTICE = ('这是基于当前自报画像和已观测条件的决策参考，匹配分不代表录用、录取或上岸概率。'
          '比较时同时查看观测维度和信息缺失，不同发展路径分别比较，不据此替你选择人生方向；'
          '报名资格和截止时间以来源原文为准。')


class DecisionWeights(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    skills: float = Field(default=0.5, ge=0)
    city: float = Field(default=0.3, ge=0)
    major: float = Field(default=0.2, ge=0)

    @model_validator(mode='after')
    def nonzero(self):
        total = self.skills + self.city + self.major
        if not math.isfinite(total) or total <= 0:
            raise ValueError('权重总和必须为有限正数')
        return self


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    opportunity_ids: list[int] | None = Field(default=None, min_length=1, max_length=6)
    weights: DecisionWeights = Field(default_factory=DecisionWeights)

    @model_validator(mode='after')
    def unique_ids(self):
        if self.opportunity_ids is not None:
            if any(i <= 0 for i in self.opportunity_ids) or len(set(self.opportunity_ids)) != len(self.opportunity_ids):
                raise ValueError('机会编号必须为不重复的正整数')
        return self


class ActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['todo', 'doing', 'done']


def latest_statement(data_kind):
    """Select immutable latest source snapshots without loading every version."""
    newer = aliased(Opportunity)
    successor = exists(select(newer.id).where(
        newer.data_kind == Opportunity.data_kind,
        newer.source_url == Opportunity.source_url,
        newer.source_record_id == Opportunity.source_record_id,
        or_(newer.version > Opportunity.version,
            and_(newer.version == Opportunity.version, newer.id > Opportunity.id)),
    ))
    return select(Opportunity).where(Opportunity.data_kind == data_kind, ~successor)


def candidate_pool(db, data_kind, selected_ids):
    """Validate explicit ids, then bound the entire evaluated opportunity pool."""
    selected = []
    if selected_ids:
        records = {o.id: o for o in db.scalars(latest_statement(data_kind).where(Opportunity.id.in_(selected_ids)))}
        if len(records) != len(selected_ids):
            raise HTTPException(422, '存在无效、数据类型不一致或已被新版替代的机会编号，请刷新机会列表')
        selected = [records[i] for i in selected_ids]
    statement = latest_statement(data_kind).order_by(Opportunity.id.desc())
    if selected_ids:
        statement = statement.where(Opportunity.id.not_in(selected_ids))
    pool = selected + list(db.scalars(statement.limit(POOL_LIMIT - len(selected))))
    return pool, selected


def compare_opportunity(profile_data, item, weights):
    """Unknown evidence stays unknown and hard exclusions never receive a score."""
    skills = {normalize_skill(s) for s in profile_data['skills']}
    required = {normalize_skill(s) for s in (item.skills or [])}
    cities = {normalize_city(c) for c in profile_data['cities']}
    matched = sorted(skills & required)
    gaps = sorted(required - skills) if skills else []
    reasons, exclusions = [], []
    if item.path not in profile_data['intents']:
        exclusions.append('该机会不在当前画像选择的发展路径中')
    if item.deadline and item.deadline < date.today():
        exclusions.append('来源记录的报名截止日期已过')
    if item.majors and profile_data['major'] not in item.majors:
        exclusions.append('自报专业与结构化专业要求不匹配，需核对原文专业目录')
    if item.minimum_degree and DEGREES.get(profile_data['degree'], -1) < DEGREES.get(item.minimum_degree, 99):
        exclusions.append('当前自报学历低于结构化最低学历要求')

    values = {
        'skills': len(matched) / len(required) if skills and required else None,
        'city': float(normalize_city(item.city) in cities) if item.city and cities else None,
        'major': float(profile_data['major'] in item.majors) if item.majors else None,
    }
    evidence = {
        'skills': (f'自报技能覆盖 {len(matched)}/{len(required)} 项；自报信息未经能力测验验证'
                   if values['skills'] is not None else
                   '尚未填写技能，不能视为不具备技能' if not skills else '来源未列出结构化技能要求'),
        'city': ('机会城市符合当前偏好' if values['city'] == 1 else
                 '机会城市不在当前偏好中' if values['city'] == 0 else '机会城市或城市偏好缺失'),
        'major': ('自报专业名称与来源结构化要求一致' if values['major'] == 1 else
                  '自报专业名称与来源结构化要求不一致' if values['major'] == 0 else '来源未提供结构化专业条件'),
    }
    components = [{'key': key, 'label': {'skills': '技能覆盖', 'city': '城市偏好', 'major': '专业条件'}[key],
                   'value': value, 'weight': weights[key], 'evidence': evidence[key]}
                  for key, value in values.items()]
    active = [(weights[key], value) for key, value in values.items() if value is not None and weights[key] > 0]
    observed_weight = sum(weight for weight, _ in active)
    score = (round(sum(weight * value for weight, value in active) / observed_weight * 100, 1)
             if len(active) >= 2 and not exclusions else None)
    if score is None and not exclusions:
        reasons.append('至少两个有观测依据且权重大于零的维度才能生成匹配分')
    reasons.extend(evidence[key] for key, value in values.items() if value is not None)
    needs_review = bool(exclusions or item.path not in ['employment', 'internship'] or
                        not item.requirements_verified or not item.deadline or
                        not item.majors or not item.minimum_degree)
    eligibility = 'ineligible' if exclusions else 'needs_review' if needs_review else 'candidate'
    suggested = ['阅读来源原文，核对学历、专业目录、应届身份、年龄、证书和报名时间，并保留核对记录']
    if gaps:
        suggested.append(f'选择 {gaps[0]} 做一次两周练习，记录成果和仍需补足的知识')
    if not skills:
        suggested.append('补充能举出课程、练习或作品依据的技能，再重新比较')
    if exclusions:
        suggested.append('先处理明确不符的条件或改选机会，当前记录不进入可报名候选清单')
    return {
        'opportunity': opportunity_dict(item), 'opportunity_version': item.version,
        'score': score, 'observed_weight': round(observed_weight, 6), 'components': components,
        'reasons': reasons, 'matched_skills': matched, 'skill_gaps': gaps,
        'skills_unknown': not bool(skills), 'needs_review': needs_review,
        'qualification_note': '仅检查已知结构化条件，不构成正式报名资格认定；复杂条件须核对来源原文',
        'eligibility': eligibility, 'exclusion_reasons': exclusions, 'suggested_actions': suggested,
        'deadline_days': (item.deadline - date.today()).days if item.deadline else None,
    }


def action(path, kind, title, detail, skill=None):
    # A semantic id remains stable across repeated runs with the same path/task.
    digest = hashlib.sha256(f'{path}:{kind}:{skill or ""}'.encode()).hexdigest()[:12]
    result = {'id': f'{path}-{digest}', 'path': path, 'title': title, 'detail': detail, 'status': 'todo'}
    if skill:
        result['skill'] = skill
    return result


def two_week_actions(path, candidates, gaps, skills_unknown, role=None):
    representative = candidates[0]['opportunity'] if candidates else None
    original = (f'优先核对《{representative["title"]}》：{representative["source_url"]}。'
                if representative else '当前清单暂无适合候选，请先从官方来源记录两条意向机会，避免使用模拟记录报名。')
    exam_note = ('逐项记录专业目录、年龄、应届身份、政治条件、证书和资格复审要求。'
                 if path in ['civil_service', 'public_institution'] else
                 '逐项记录报考专业、考试科目、招生人数、学历条件与复试要求。'
                 if path == 'postgraduate' else '逐项记录工作内容、学历、技能、实习时段和材料要求。')
    tasks = [action(path, 'verify', '第 1–3 天：核对来源与报名条件',
                    original + exam_note + '记录原文链接、核对日期、截止时间及尚未确认的条件。')]
    details = {
        'employment': '第 4–7 天：选择一个与专业有关的实践问题并完成小作品；第 8–14 天：整理代码、数据来源、成果说明和一页简历，请同学或老师给出一次反馈。',
        'internship': '第 4–7 天：整理可参加实习的起止时间和每周可投入时间，完成一个课程成果说明；第 8–14 天：对照两个实习岗位修改简历并准备一次模拟面试。',
        'postgraduate': '第 4–7 天：对比两所意向院校的招生简章、考试科目、费用和学制；第 8–14 天：试做一组对应科目练习，记录困难与投入时间，再调整备考计划。',
        'civil_service': '第 4–7 天：对比两条官方岗位公告的资格条件与考试科目；第 8–14 天：完成一组公开练习并记录错因和用时，据此判断下一阶段学习重点。',
        'public_institution': '第 4–7 天：对比两条事业单位官方招聘公告的岗位类型、资格条件和笔试科目；第 8–14 天：完成一次相关科目练习或专业技能展示，记录反馈后调整计划。',
    }
    tasks.append(action(path, 'explore', '第 4–14 天：完成一次路径探索任务',
                        details.get(path, '两周内整理两个官方机会的条件与所需材料，完成一次相关练习并记录收获。')))
    for entry in gaps[:2]:
        skill = entry['skill']
        tasks.append(action(path, 'skill', f'两周练习：{skill}',
                            f'当前 {entry["count"]} 个该路径候选提及 {skill}。第 1–3 天梳理基础概念，第 4–7 天完成一个练习，'
                            '第 8–14 天将练习应用到小案例并保存成果；可按实际课业时间调整，并在画像中补充证据。', skill))
    if skills_unknown:
        tasks.append(action(path, 'evidence', '补充带依据的技能画像',
                            '从最近的课程作业、项目或实习中记录能举例说明的技能；尚未填写的技能属于未知，不等于不会。'))
    if role:
        role_label = role.get('label') or role.get('name') or '当前探索角色'
        activity = (role.get('actions') or ['选一个愿意尝试的相关任务'])[0]
        tasks.append(action(path, 'interest', f'结合{role_label}做一次兴趣验证',
                            f'兴趣问卷仅用于自我探索。可以尝试：{activity}。记录完成前后的兴趣、难点和成就感；不要把角色当作职业限制。'))
    return tasks


def interest_context(db, user_id):
    """Interest integration is optional; no role ever changes eligibility or score."""
    try:
        from .interests import ROLE_BY_CODE, role_result
    except ImportError:
        return {'interest_response_id': None, 'role': None}
    response = role_result(db, user_id)
    if not response:
        return {'interest_response_id': None, 'role': None}
    role = None
    if not response.get('hidden') and response.get('display_role') in ROLE_BY_CODE:
        role = deepcopy(ROLE_BY_CODE[response['display_role']])
        role.update(rule_version=response.get('rule_version'),
                    instrument_version=response.get('instrument_version'),
                    profile_version=response.get('profile_version'),
                    manual_override=response.get('manual_override', False))
    return {'interest_response_id': response['response_id'], 'role': role,
            'interest_rule_version': response.get('rule_version'),
            'interest_profile_version': response.get('profile_version')}


def decision_view(run):
    result = deepcopy(run.results)
    for item in result.get('action_plan', []):
        item['status'] = (run.action_states or {}).get(item['id'], {}).get('status', 'todo')
    return {**result, 'id': run.id, 'profile_version': run.profile_version,
            'model_version': run.model_version, 'generated_at': run.generated_at,
            'data_kind': run.data_kind, 'weights': run.configuration['weights']}


@router.post('/compare')
def compare(payload: DecisionInput, data_kind: str = Query('public', pattern='^(demo|public)$'),
            user=Depends(current_user), db=Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)))
    if not profile:
        raise HTTPException(422, '请先保存个人画像，再生成决策方案')
    data, weights = profile_dict(profile), payload.weights.model_dump()
    pool, selected = candidate_pool(db, data_kind, payload.opportunity_ids)
    all_results = [compare_opportunity(data, item, weights) for item in pool]
    by_id = {item['opportunity']['id']: item for item in all_results}
    context = interest_context(db, user.id)
    role = context.get('role')
    paths, plan, grouped = [], [], []
    for path in dict.fromkeys(data['intents']):
        candidates = [r for r in all_results if r['opportunity']['path'] == path and r['eligibility'] != 'ineligible']
        # Sorting is strictly within this path, never an aggregate life-path score.
        candidates.sort(key=lambda r: (r['score'] is None, -(r['score'] or 0), r['opportunity']['id']))
        grouped.append(candidates)
        gap_counts = Counter(skill for r in candidates for skill in r['skill_gaps'])
        gaps = [{'skill': skill, 'count': count} for skill, count in sorted(gap_counts.items(), key=lambda x: (-x[1], x[0]))]
        tasks = two_week_actions(path, candidates, gaps, not data['skills'], role)
        plan.extend(tasks)
        paths.append({'path': path, 'label': PATH_LABELS.get(path, path), 'candidate_count': len(candidates),
                      'review_count': sum(r['needs_review'] for r in candidates),
                      'known_deadlines': sum(r['deadline_days'] is not None for r in candidates),
                      'skill_gaps': gaps, 'next_actions': [t['title'] for t in tasks],
                      'readiness': ('暂无候选：可以先补充画像并完成路径探索，当前不评价准备程度' if not candidates else
                                    '已有候选线索：先核对原文资格，再按具体技能差距安排练习；自报技能不等于已验证能力')})
    if selected:
        comparisons = [by_id[item.id] for item in selected]
    else:
        # Round-robin preserves visibility of each selected path in the shortlist.
        comparisons = []
        for depth in range(COMPARISON_LIMIT):
            for group in grouped:
                if depth < len(group) and len(comparisons) < COMPARISON_LIMIT:
                    comparisons.append(group[depth])
            if len(comparisons) >= COMPARISON_LIMIT:
                break
    evidence = {
        'interest_response_id': context.get('interest_response_id'), 'role': role,
        'interest_rule_version': context.get('interest_rule_version'),
        'interest_profile_version': context.get('interest_profile_version'),
        'summary': f'按你选择的 {len(paths)} 条发展路径分别整理线索与两周行动；本次检查最多 {POOL_LIMIT} 条最新机会记录。',
        'paths': paths, 'comparisons': comparisons, 'action_plan': plan, 'notice': NOTICE,
        'evaluated_candidate_count': len(pool),
    }
    run = DecisionRun(user_id=user.id, profile_id=profile.id, profile_version=profile.version,
                      model_version=MODEL_VERSION, data_kind=data_kind,
                      configuration={'weights': weights, 'opportunity_ids': payload.opportunity_ids,
                                     'candidate_limit': POOL_LIMIT, 'comparison_limit': COMPARISON_LIMIT},
                      results=jsonable_encoder(evidence), action_states={})
    db.add(run)
    db.commit()
    return decision_view(run)


@router.get('/history')
def history(user=Depends(current_user), db=Depends(get_db)):
    runs = db.scalars(select(DecisionRun).where(DecisionRun.user_id == user.id).order_by(DecisionRun.id.desc()).limit(30))
    return [decision_view(run) for run in runs]


def owned_run(db, user_id, run_id, lock=False):
    statement = select(DecisionRun).where(DecisionRun.id == run_id, DecisionRun.user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    run = db.scalar(statement)
    if not run:
        raise HTTPException(404, '决策记录不存在')
    return run


@router.get('/{run_id}')
def get_decision(run_id: int, user=Depends(current_user), db=Depends(get_db)):
    return decision_view(owned_run(db, user.id, run_id))


@router.patch('/{run_id}/actions/{action_id}')
def update_action(run_id: int, action_id: str, payload: ActionInput,
                  user=Depends(current_user), db=Depends(get_db)):
    run = owned_run(db, user.id, run_id, lock=True)
    if action_id not in {item['id'] for item in run.results.get('action_plan', [])}:
        raise HTTPException(404, '行动项不存在')
    states = deepcopy(run.action_states or {})
    states[action_id] = {'status': payload.status}
    run.action_states = states
    db.commit()
    return decision_view(run)
