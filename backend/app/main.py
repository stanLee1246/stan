import os
import secrets
from collections import Counter
from datetime import date, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .database import get_db
from .models import AuditEvent, Experience, IngestionBatch, LoginSession, Opportunity, Outcome, Profile, ProfileTag, Recommendation, User, now
from .schemas import Credentials, ExperienceInput, ImportInput, ModerationInput, OpportunityInput, ProfileInput, Register
from .security import hash_password, token_hash, verify_password
from .services import PATH_LABELS, import_outcomes, normalize_city, normalize_skill, opportunity_dict, profile_dict, score_opportunity

app = FastAPI(title='学生职业发展辅助决策平台', version='0.1.0')
bearer = HTTPBearer(auto_error=False)
DUMMY_PASSWORD_HASH = hash_password('unavailable-account-placeholder')


def current_user(auth: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    if not auth:
        raise HTTPException(401, '请先登录')
    session = db.get(LoginSession, token_hash(auth.credentials))
    if not session or session.expires_at <= now():
        raise HTTPException(401, '登录已过期，请重新登录')
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, '账户不存在')
    return user


def administrator(user=Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, '仅管理员可执行此操作')
    return user


def user_dict(user):
    return {'id': user.id, 'username': user.username, 'nickname': user.nickname, 'role': user.role}


@app.get('/api/health')
def health(db=Depends(get_db)):
    try:
        db.execute(select(User.id).limit(1))
    except SQLAlchemyError:
        raise HTTPException(503, '数据库未就绪，请检查本地配置并运行数据库迁移')
    return {'status': 'ok', 'database': db.bind.dialect.name, 'version': app.version}


@app.post('/api/auth/register', status_code=201)
def register(payload: Register, db=Depends(get_db)):
    user = User(username=payload.username, nickname=payload.nickname.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '用户名已被使用')
    return user_dict(user)


@app.post('/api/auth/login')
def login(payload: Credentials, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    # Always perform the password KDF to reduce account-existence timing differences.
    stored = user.password_hash if user else DUMMY_PASSWORD_HASH
    if not verify_password(payload.password, stored) or not user:
        raise HTTPException(401, '用户名或密码错误')
    token = secrets.token_urlsafe(32)
    expiry = now() + timedelta(hours=int(os.getenv('SESSION_HOURS', '24')))
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    db.add(LoginSession(token_hash=token_hash(token), user_id=user.id, expires_at=expiry))
    db.commit()
    return {'token': token, 'expires_at': expiry, 'user': user_dict(user)}


@app.post('/api/auth/logout')
def logout(auth: HTTPAuthorizationCredentials = Depends(bearer), user=Depends(current_user), db=Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(auth.credentials)))
    db.commit()
    return {'message': '已退出'}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return user_dict(user)


@app.get('/api/dictionaries')
def dictionaries():
    return {'paths': PATH_LABELS,
            'majors': ['数据科学与大数据技术', '软件工程', '计算机科学与技术'],
            'cities': ['衡阳', '长沙', '广州', '深圳', '武汉'],
            'skills': ['Python', 'SQL', 'MySQL', 'pandas', 'Excel', 'Vue', 'ECharts', 'Java', 'Spark']}


@app.get('/api/profile')
def get_profile(user=Depends(current_user), db=Depends(get_db)):
    return profile_dict(db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None))))


@app.get('/api/profile/history')
def profile_history(user=Depends(current_user), db=Depends(get_db)):
    return [profile_dict(p) for p in db.scalars(select(Profile).where(Profile.user_id == user.id).order_by(Profile.version.desc()))]


@app.put('/api/profile')
def save_profile(payload: ProfileInput, user=Depends(current_user), db=Depends(get_db)):
    changed = db.execute(update(User).where(User.id == user.id, User.profile_revision == payload.expected_version)
                         .values(profile_revision=User.profile_revision + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, '画像已在其他页面更新，请刷新后重试')
    timestamp = now()
    db.execute(update(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)).values(valid_to=timestamp))
    values = payload.model_dump(exclude={'expected_version', 'skills', 'cities', 'intents'})
    profile = Profile(user_id=user.id, version=payload.expected_version + 1, valid_from=timestamp, recorded_at=timestamp, **values)
    for kind in ['skills', 'cities', 'intents']:
        terms = getattr(payload, kind)
        terms = [normalize_skill(v) if kind == 'skills' else normalize_city(v) if kind == 'cities' else v for v in terms]
        profile.tags.extend(ProfileTag(kind=kind, value=v) for v in dict.fromkeys(terms))
    db.add(profile)
    db.commit()
    return profile_dict(profile)


def latest_opportunities(db, data_kind):
    items = db.scalars(select(Opportunity).where(Opportunity.data_kind == data_kind).order_by(Opportunity.version.desc(), Opportunity.id.desc()))
    seen, latest = set(), []
    for item in items:
        key = (item.source_url, item.source_record_id)
        if key not in seen:
            seen.add(key)
            latest.append(item)
    return latest


@app.get('/api/opportunities')
def opportunities(data_kind: str = Query('public', pattern='^(demo|public)$'), path: str | None = None,
                  city: str | None = None, q: str = '', include_expired: bool = False, db=Depends(get_db)):
    items = latest_opportunities(db, data_kind)
    return [opportunity_dict(o) for o in items if (not path or o.path == path) and
            (not city or o.city == normalize_city(city)) and
            (not q or q.casefold() in (o.title + o.organization + o.description).casefold()) and
            (include_expired or o.deadline is None or o.deadline >= date.today())][:200]


@app.post('/api/admin/opportunities', status_code=201)
def save_opportunity(payload: OpportunityInput, user=Depends(administrator), db=Depends(get_db)):
    values = payload.model_dump()
    values['source_url'] = str(payload.source_url)
    values['skills'] = list(dict.fromkeys(normalize_skill(s) for s in values['skills']))
    values['city'] = normalize_city(values['city']) if values['city'] else None
    existing = db.scalar(select(Opportunity).where(Opportunity.source_url == values['source_url'],
                         Opportunity.source_record_id == payload.source_record_id).order_by(Opportunity.version.desc()))
    if existing and existing.data_kind != payload.data_kind:
        raise HTTPException(422, '机会版本不得改变模拟/真实类型，请使用独立来源编号')
    item = Opportunity(**values, version=existing.version + 1 if existing else 1)
    db.add(item)
    try:
        db.flush()
        db.add(AuditEvent(actor_id=user.id, action='opportunity_version', target_id=item.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '该机会被同时更新，请重试')
    return opportunity_dict(item)


@app.post('/api/recommendations')
def recommend(data_kind: str = Query('public', pattern='^(demo|public)$'), user=Depends(current_user), db=Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id, Profile.valid_to.is_(None)))
    if not profile:
        raise HTTPException(422, '请先保存个人画像')
    results = [r for o in latest_opportunities(db, data_kind) if (r := score_opportunity(profile, o)) is not None]
    # Each path is a separate candidate list; scores never select one life path for the user.
    results.sort(key=lambda r: (r['opportunity']['path'], -(r['score'] if r['score'] is not None else -1), r['opportunity']['id']))
    run = Recommendation(user_id=user.id, profile_id=profile.id, profile_version=profile.version,
                         data_kind=data_kind, results=jsonable_encoder(results[:100]))
    db.add(run)
    db.commit()
    return {'id': run.id, 'profile_version': run.profile_version, 'model_version': run.model_version,
            'generated_at': run.generated_at, 'results': run.results}


@app.get('/api/recommendations/history')
def recommendation_history(user=Depends(current_user), db=Depends(get_db)):
    runs = db.scalars(select(Recommendation).where(Recommendation.user_id == user.id).order_by(Recommendation.id.desc()).limit(30))
    return [{'id': r.id, 'profile_version': r.profile_version, 'model_version': r.model_version,
             'generated_at': r.generated_at, 'data_kind': r.data_kind, 'results': r.results} for r in runs]


@app.get('/api/data-sources')
def data_sources(data_kind: str = Query('authorized', pattern='^(demo|authorized)$'), db=Depends(get_db)):
    return list(db.scalars(select(Outcome.source_name).where(Outcome.data_kind == data_kind).distinct().order_by(Outcome.source_name)))


@app.get('/api/dashboard')
def dashboard(data_kind: str = Query('authorized', pattern='^(demo|authorized)$'), major: str | None = None,
              graduation_year: int | None = None, source_name: str | None = None,
              observed_on: date | None = None, db=Depends(get_db)):
    cutoff = observed_on or date.today()
    all_rows = list(db.scalars(select(Outcome).where(Outcome.data_kind == data_kind, Outcome.observed_on <= cutoff)
                             .order_by(Outcome.observed_on.desc(), Outcome.id.desc())))
    sources = sorted(set(o.source_name for o in all_rows))
    if not source_name and len(sources) > 1:
        raise HTTPException(422, '存在多个来源，请选择一个来源；不同样本不得直接相加')
    selected_source = source_name or (sources[0] if sources else None)
    seen, rows = set(), []
    for row in all_rows:
        if row.source_name != selected_source or row.student_key in seen:
            continue
        seen.add(row.student_key)
        if (not major or row.major == major) and (not graduation_year or row.graduation_year == graduation_year):
            rows.append(row)
    private = data_kind == 'authorized'
    too_small = private and 0 < len(rows) < 5

    def distribution(attr):
        counts = Counter(getattr(r, attr) or '未知' for r in rows)
        # Suppress the entire breakdown when any cell is small to prevent subtraction from totals.
        hidden = private and any(n < 5 for n in counts.values())
        if hidden:
            return [], True
        return [{'key': k, 'label': PATH_LABELS.get(k, k), 'count': n} for k, n in sorted(counts.items(), key=lambda x: -x[1])], False

    paths, path_hidden = distribution('path')
    cities, city_hidden = distribution('city')
    years, year_hidden = distribution('graduation_year')
    return {'data_kind': data_kind, 'source_name': selected_source, 'observed_on': cutoff,
            'sample_size': None if too_small else len(rows), 'privacy_suppressed': too_small,
            'paths': paths, 'cities': cities, 'years': years,
            'suppressed_dimensions': [k for k, h in [('paths', path_hidden), ('cities', city_hidden), ('years', year_hidden)] if h],
            'latest_observation': max((r.observed_on for r in rows), default=None),
            'definition': '同一来源下每名匿名毕业生在截止观察日的最新主要实际去向；实习与备考意向不计入实际去向。',
            'notice': '模拟数据仅用于功能演示' if data_kind == 'demo' else '授权样本不代表全校总体；小组不足5人时隐藏整项分布',
            'batch_ids': sorted(set(r.batch_id for r in rows)) if not too_small else []}


@app.get('/api/school')
def school():
    return {'name': '湖南交通工程学院', 'metrics': [], 'notice': '暂无已核实的办学规模及就业指标，请录入带年份、统计口径和分母的公开报告后展示。',
            'sources': [{'name': '学校官网', 'url': 'https://hnjt.edu.cn/'},
                        {'name': '2023–2024本科教学质量报告入口（待人工核验）', 'url': 'https://hnjt.edu.cn/show/22091.html'},
                        {'name': '中国研究生招生信息网', 'url': 'https://yz.chsi.com.cn/'},
                        {'name': '国家大学生就业服务平台', 'url': 'https://www.ncss.cn/'}]}


def experience_dict(post):
    return {k: getattr(post, k) for k in ['id', 'public_nickname', 'title', 'body', 'graduation_year', 'city',
                                        'path', 'status', 'moderation_note', 'created_at', 'data_kind']}


@app.get('/api/experiences')
def experiences(db=Depends(get_db)):
    return [experience_dict(p) for p in db.scalars(select(Experience).where(Experience.status == 'approved', Experience.public_consent.is_(True)).order_by(Experience.id.desc()).limit(100))]


@app.get('/api/experiences/mine')
def my_experiences(user=Depends(current_user), db=Depends(get_db)):
    return [experience_dict(p) for p in db.scalars(select(Experience).where(Experience.author_id == user.id).order_by(Experience.id.desc()))]


@app.post('/api/experiences', status_code=201)
def submit_experience(payload: ExperienceInput, user=Depends(current_user), db=Depends(get_db)):
    if not payload.public_consent:
        raise HTTPException(422, '公开经验需要单独授权')
    post = Experience(author_id=user.id, public_nickname=user.nickname, **payload.model_dump())
    db.add(post)
    db.commit()
    return experience_dict(post)


@app.delete('/api/experiences/{post_id}')
def withdraw_experience(post_id: int, user=Depends(current_user), db=Depends(get_db)):
    post = db.get(Experience, post_id)
    if not post or post.author_id != user.id:
        raise HTTPException(404, '经验不存在')
    post.status = 'withdrawn'
    post.public_consent = False
    db.commit()
    return {'message': '公开经验已撤回'}


@app.post('/api/admin/import/outcomes')
def import_csv(payload: ImportInput, user=Depends(administrator), db=Depends(get_db)):
    result = import_outcomes(db, user.id, payload)
    db.add(AuditEvent(actor_id=user.id, action='import_outcomes', target_id=result['batch_id']))
    db.commit()
    return result


@app.get('/api/admin/batches')
def batches(user=Depends(administrator), db=Depends(get_db)):
    return [{k: getattr(b, k) for k in ['id', 'source_name', 'data_kind', 'content_hash', 'cleaning_version', 'quality', 'created_at']}
            for b in db.scalars(select(IngestionBatch).order_by(IngestionBatch.id.desc()).limit(50))]


@app.get('/api/admin/experiences')
def pending_experiences(user=Depends(administrator), db=Depends(get_db)):
    return [experience_dict(p) for p in db.scalars(select(Experience).where(Experience.status == 'pending').order_by(Experience.id))]


@app.post('/api/admin/experiences/{post_id}/moderate')
def moderate(post_id: int, payload: ModerationInput, user=Depends(administrator), db=Depends(get_db)):
    post = db.get(Experience, post_id)
    if not post:
        raise HTTPException(404, '经验不存在')
    if post.status != 'pending' or not post.public_consent:
        raise HTTPException(409, '仅待审核且仍授权的经验可审核')
    post.status, post.moderation_note = payload.status, payload.note
    db.add(AuditEvent(actor_id=user.id, action=f'experience_{payload.status}', target_id=post_id))
    db.commit()
    return experience_dict(post)


@app.get('/api/admin/audit')
def audit(user=Depends(administrator), db=Depends(get_db)):
    return [{k: getattr(e, k) for k in ['id', 'actor_id', 'action', 'target_id', 'created_at']}
            for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(100))]
