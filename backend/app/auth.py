"""Shared authentication dependencies for feature routers."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import get_db
from .models import LoginSession, User, now
from .security import token_hash

bearer = HTTPBearer(auto_error=False)


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
