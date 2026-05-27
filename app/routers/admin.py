"""admin 后台 API。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_db
from app.models import (
    ALL_ROLES,
    ROLE_ADMIN,
    Answer,
    Attempt,
    Question,
    Task,
    User,
)
from app.schemas import (
    AttemptSummary,
    UserAdminUpdate,
    UserPublic,
)
from app.security import hash_password
from app.services.csv_export import stream_answers_csv, stream_attempts_csv
from app.services.storage import public_url_of

admin_router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_role(ROLE_ADMIN))]
)


# ---------- users ----------

@admin_router.get("/users", response_model=list[UserPublic])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id.asc())).all())


@admin_router.patch("/users/{user_id}", response_model=UserPublic)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    actor: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if payload.role is not None:
        if payload.role not in ALL_ROLES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"无效角色：{payload.role}")
        # 防止把自己降级（避免没人能管系统）
        if u.id == actor.id and payload.role != ROLE_ADMIN:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能把自己降级")
        u.role = payload.role

    if payload.is_active is not None:
        if u.id == actor.id and not payload.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己")
        u.is_active = 1 if payload.is_active else 0

    if payload.new_password is not None:
        u.password_hash = hash_password(payload.new_password)

    if payload.display_name is not None:
        u.display_name = payload.display_name or None

    db.commit()
    db.refresh(u)
    return u


# ---------- attempts ----------

@admin_router.get("/attempts", response_model=list[AttemptSummary])
def list_attempts(
    task_code: str | None = Query(None),
    user_id: int | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> list[AttemptSummary]:
    stmt = (
        select(Attempt, User, Task)
        .join(User, Attempt.user_id == User.id)
        .join(Task, Attempt.task_id == Task.id)
    )
    if task_code:
        stmt = stmt.where(Task.code == task_code)
    if user_id:
        stmt = stmt.where(Attempt.user_id == user_id)
    if status_:
        stmt = stmt.where(Attempt.status == status_)
    stmt = stmt.order_by(Attempt.started_at.desc())

    rows = db.execute(stmt).all()
    out: list[AttemptSummary] = []
    for a, u, t in rows:
        out.append(
            AttemptSummary(
                id=a.id,
                user_id=u.id,
                username=u.username,
                display_name=u.display_name,
                task_id=t.id,
                task_code=t.code,
                task_name=t.name,
                status=a.status,
                batch_index=a.batch_index,
                score=a.score,
                total=a.total,
                correct=a.correct,
                started_at=a.started_at,
                submitted_at=a.submitted_at,
            )
        )
    return out


@admin_router.get("/attempts/{attempt_id}")
def get_attempt_detail(
    attempt_id: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    a = db.get(Attempt, attempt_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "答题记录不存在")
    user = db.get(User, a.user_id)
    task = db.get(Task, a.task_id)
    questions = db.scalars(
        select(Question)
        .where(Question.task_id == a.task_id, Question.is_deleted == 0)
        .order_by(Question.order_index, Question.id)
    ).all()
    answers = db.scalars(select(Answer).where(Answer.attempt_id == a.id)).all()
    amap = {an.question_id: an for an in answers}
    rows = []
    for q in questions:
        an = amap.get(q.id)
        rows.append({
            "question_id": q.id,
            "order_index": q.order_index,
            "batch_index": q.batch_index,
            "batch_position": q.batch_position,
            "image_url": public_url_of(q.image_path),
            "ground_truth": q.ground_truth,
            "answer_text": an.answer_text if an else "",
            "note": an.note if an else "",
            "review_flag": bool(an and an.review_flag),
            "time_spent_seconds": an.time_spent_seconds if an else 0,
            "is_correct": bool(an and an.is_correct),
        })
    return {
        "id": a.id,
        "user": {
            "id": user.id, "username": user.username, "display_name": user.display_name,
        },
        "task": {"id": task.id, "code": task.code, "name": task.name},
        "status": a.status,
        "batch_index": a.batch_index,
        "score": a.score,
        "total": a.total,
        "correct": a.correct,
        "started_at": a.started_at,
        "updated_at": a.updated_at,
        "submitted_at": a.submitted_at,
        "rows": rows,
    }


# ---------- exports ----------

def _csv_response(stream, filename: str) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@admin_router.get("/exports/attempts.csv")
def export_attempts_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    fname = f"attempts_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return _csv_response(stream_attempts_csv(db), fname)


@admin_router.get("/exports/answers.csv")
def export_answers_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    fname = f"answers_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return _csv_response(stream_answers_csv(db), fname)
