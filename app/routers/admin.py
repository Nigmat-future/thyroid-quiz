"""admin 后台 API。"""

from __future__ import annotations

from datetime import datetime

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
    AdminAttemptDetail,
    AdminAttemptDetailRow,
    AdminAttemptDetailTask,
    AdminAttemptDetailUser,
    AdminAttemptMetrics,
    AdminUserSummary,
    AttemptSummary,
    UserAdminUpdate,
    UserPublic,
)
from app.security import hash_password
from app.services.admin_user_metrics import summarize_users_metrics
from app.services.attempt_metrics import (
    AnswerMetricRow,
    is_answer_correct,
    malignancy_score_for,
    summarize_attempt_metrics,
    truth_binary_for,
)
from app.services.csv_export import stream_answers_csv, stream_attempts_csv
from app.services.fna import parse_source_note
from app.services.storage import public_url_of

admin_router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_role(ROLE_ADMIN))]
)


# ---------- users ----------

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
            total=metrics_by_user_id[user.id].total,
            answered=metrics_by_user_id[user.id].answered,
            correct=metrics_by_user_id[user.id].correct,
            accuracy=metrics_by_user_id[user.id].accuracy,
            auc=metrics_by_user_id[user.id].auc,
            auc_positive=metrics_by_user_id[user.id].auc_positive,
            auc_negative=metrics_by_user_id[user.id].auc_negative,
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

def _questions_of_attempt(db: Session, attempt: Attempt) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .where(
                Question.task_id == attempt.task_id,
                Question.batch_index == attempt.batch_index,
                Question.is_deleted == 0,
            )
            .order_by(Question.batch_position, Question.order_index, Question.id)
        ).all()
    )


def _answer_map(db: Session, attempt_id: int) -> dict[int, Answer]:
    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt_id)).all()
    return {answer.question_id: answer for answer in answers}


def _metric_rows(
    questions: list[Question],
    answers_by_question: dict[int, Answer],
) -> list[AnswerMetricRow]:
    return [
        AnswerMetricRow(
            answer_text=answers_by_question[question.id].answer_text
            if question.id in answers_by_question
            else "",
            ground_truth=question.ground_truth,
        )
        for question in questions
    ]


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
        questions = _questions_of_attempt(db, a)
        answers_by_question = _answer_map(db, a.id)
        metrics = summarize_attempt_metrics(_metric_rows(questions, answers_by_question))
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
                score=metrics.accuracy,
                total=metrics.total,
                correct=metrics.correct,
                answered=metrics.answered,
                auc=metrics.auc,
                started_at=a.started_at,
                submitted_at=a.submitted_at,
            )
        )
    return out


@admin_router.get("/attempts/{attempt_id}", response_model=AdminAttemptDetail)
def get_attempt_detail(
    attempt_id: int, db: Session = Depends(get_db)
) -> AdminAttemptDetail:
    a = db.get(Attempt, attempt_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "答题记录不存在")
    user = db.get(User, a.user_id)
    task = db.get(Task, a.task_id)
    questions = _questions_of_attempt(db, a)
    amap = _answer_map(db, a.id)
    metrics = summarize_attempt_metrics(_metric_rows(questions, amap))
    rows: list[AdminAttemptDetailRow] = []
    for q in questions:
        an = amap.get(q.id)
        answer_text = an.answer_text if an else ""
        source_center, source_file_path = parse_source_note(q.note)
        rows.append(
            AdminAttemptDetailRow(
                question_id=q.id,
                order_index=q.order_index,
                batch_index=q.batch_index,
                batch_position=q.batch_position,
                image_url=public_url_of(q.image_path),
                ground_truth=q.ground_truth,
                answer_text=answer_text,
                note=an.note if an else "",
                review_flag=bool(an and an.review_flag),
                time_spent_seconds=an.time_spent_seconds if an else 0,
                is_correct=is_answer_correct(answer_text, q.ground_truth),
                truth_binary=truth_binary_for(q.ground_truth),
                doctor_malignancy_score=malignancy_score_for(answer_text),
                source_center=source_center,
                source_file_path=source_file_path,
            )
        )
    return AdminAttemptDetail(
        id=a.id,
        user=AdminAttemptDetailUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
        ),
        task=AdminAttemptDetailTask(id=task.id, code=task.code, name=task.name),
        status=a.status,
        batch_index=a.batch_index,
        score=metrics.accuracy,
        total=metrics.total,
        correct=metrics.correct,
        started_at=a.started_at,
        updated_at=a.updated_at,
        submitted_at=a.submitted_at,
        metrics=AdminAttemptMetrics(
            total=metrics.total,
            answered=metrics.answered,
            correct=metrics.correct,
            accuracy=metrics.accuracy,
            auc=metrics.auc,
            auc_positive=metrics.auc_positive,
            auc_negative=metrics.auc_negative,
        ),
        rows=rows,
    )


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
