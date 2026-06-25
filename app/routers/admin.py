"""admin 后台 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import ALL_ROLES, CAREER_OTHER, ROLE_ADMIN, Answer, Attempt, Question, Task, User
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
            work_hospital=user.work_hospital,
            physician_title=user.physician_title,
            career_stage=user.career_stage,
            career_stage_other=user.career_stage_other,
            license_years=user.license_years,
            profile_complete=user.profile_complete,
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

    if payload.work_hospital is not None:
        user.work_hospital = payload.work_hospital or None

    if payload.physician_title is not None:
        user.physician_title = payload.physician_title or None

    if payload.career_stage is not None:
        user.career_stage = payload.career_stage or None
        if user.career_stage != CAREER_OTHER:
            user.career_stage_other = None

    if payload.career_stage_other is not None:
        user.career_stage_other = payload.career_stage_other or None

    if payload.license_years is not None:
        user.license_years = payload.license_years

    db.commit()
    db.refresh(user)
    return user


@admin_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    actor: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")

    # 删该用户的 attempts + answers
    attempt_ids = list(db.scalars(select(Attempt.id).where(Attempt.user_id == user_id)))
    if attempt_ids:
        db.execute(delete(Answer).where(Answer.attempt_id.in_(attempt_ids)))
        db.execute(delete(Attempt).where(Attempt.user_id == user_id))

    # 删该用户创建的 task（含其下的 attempts/answers/questions）
    task_ids = list(db.scalars(select(Task.id).where(Task.created_by == user_id)))
    for task_id in task_ids:
        task_attempt_ids = list(db.scalars(select(Attempt.id).where(Attempt.task_id == task_id)))
        if task_attempt_ids:
            db.execute(delete(Answer).where(Answer.attempt_id.in_(task_attempt_ids)))
            db.execute(delete(Attempt).where(Attempt.task_id == task_id))
        db.execute(delete(Question).where(Question.task_id == task_id))
        db.execute(delete(Task).where(Task.id == task_id))

    # 删该用户上传的其余题目（归属于其他 task）
    db.execute(delete(Question).where(Question.uploaded_by == user_id))

    db.delete(user)
    db.commit()


admin_router.include_router(admin_attempts_router)
