"""admin 后台 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import ALL_ROLES, ROLE_ADMIN, User
from app.routers.admin_attempts import admin_attempts_router
from app.schemas import UserAdminUpdate, UserPublic
from app.schemas_admin import AdminUserSummary
from app.security import hash_password
from app.services.admin_user_metrics import summarize_users_metrics

admin_router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_role(ROLE_ADMIN))]
)


@admin_router.get("/users", response_model=list[AdminUserSummary])
def list_users(db: Session = Depends(get_db)) -> list[AdminUserSummary]:
    users = list(db.scalars(select(User).order_by(User.id.asc())).all())
    metrics_by_user_id = summarize_users_metrics(db, users)
    return [
        AdminUserSummary(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
            submitted_attempts=metrics_by_user_id[user.id].submitted_attempts,
            in_progress_attempts=metrics_by_user_id[user.id].in_progress_attempts,
            submitted_answered=metrics_by_user_id[user.id].submitted_answered,
            in_progress_answered=metrics_by_user_id[user.id].in_progress_answered,
            total=metrics_by_user_id[user.id].total,
            answered=metrics_by_user_id[user.id].answered,
            correct=metrics_by_user_id[user.id].correct,
            accuracy=metrics_by_user_id[user.id].accuracy,
            auc=metrics_by_user_id[user.id].auc,
            auc_positive=metrics_by_user_id[user.id].auc_positive,
            auc_negative=metrics_by_user_id[user.id].auc_negative,
            uncertain=metrics_by_user_id[user.id].uncertain,
            ppv=metrics_by_user_id[user.id].ppv,
            npv=metrics_by_user_id[user.id].npv,
            sensitivity=metrics_by_user_id[user.id].sensitivity,
            specificity=metrics_by_user_id[user.id].specificity,
        )
        for user in users
    ]


@admin_router.patch("/users/{user_id}", response_model=UserPublic)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    actor: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if payload.role is not None:
        if payload.role not in ALL_ROLES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"无效角色：{payload.role}")
        if user.id == actor.id and payload.role != ROLE_ADMIN:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能把自己降级")
        user.role = payload.role

    if payload.is_active is not None:
        if user.id == actor.id and not payload.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己")
        user.is_active = 1 if payload.is_active else 0

    if payload.new_password is not None:
        user.password_hash = hash_password(payload.new_password)

    if payload.display_name is not None:
        user.display_name = payload.display_name or None

    db.commit()
    db.refresh(user)
    return user


admin_router.include_router(admin_attempts_router)
