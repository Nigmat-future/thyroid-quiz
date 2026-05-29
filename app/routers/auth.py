"""鉴权 API：注册 / 登录 / 登出 / 当前用户。"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import ROLE_DOCTOR, User
from app.schemas import UserCreate, UserLogin, UserPublic
from app.security import hash_password, verify_password

# 用户名只允许字母数字下划线，3-32 位
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
me_router = APIRouter(prefix="/api", tags=["auth"])


@auth_router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, request: Request, db: Session = Depends(get_db)) -> User:
    if not USERNAME_RE.match(payload.username):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "用户名仅允许 3-32 位字母数字下划线"
        )

    exists = db.scalar(select(User).where(User.username == payload.username))
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or None,
        role=ROLE_DOCTOR,
        is_active=1,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # 以数据库唯一约束为最终防线，兜住并发注册同名用户的竞争窗口。
        exists_after_commit = db.scalar(select(User.id).where(User.username == payload.username))
        if exists_after_commit is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用") from None
        raise
    db.refresh(user)

    # 注册成功即自动登录
    request.session.clear()
    request.session["user_id"] = user.id
    return user


@auth_router.post("/login", response_model=UserPublic)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")

    request.session.clear()
    request.session["user_id"] = user.id
    return user


@auth_router.post("/logout")
def logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


@me_router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)) -> User:
    return user
