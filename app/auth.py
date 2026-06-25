"""鉴权依赖：从 session 取出当前用户，提供 role 守卫工厂。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ALL_ROLES, User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """从 starlette session cookie 解出 user_id，查库返回 User；否则 401。"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        # session 指向的用户不存在或被禁用 — 清掉脏 session
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="会话已失效")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """像 get_current_user，但未登录时返回 None 而不是 401。"""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    """依赖工厂：限制路由只允许指定角色访问。"""
    invalid = [r for r in roles if r not in ALL_ROLES]
    if invalid:
        raise ValueError(f"无效角色: {invalid}")

    allowed = set(roles)

    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        if not user.profile_complete:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请先完善个人资料")
        return user

    return dep


def require_profile_complete(user: User = Depends(get_current_user)) -> User:
    """已登录且个人资料完整；否则 403。"""
    if not user.profile_complete:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请先完善个人资料")
    return user
