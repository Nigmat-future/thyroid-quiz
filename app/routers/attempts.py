"""答题 API：创建/续答 attempt、保存单题、提交、查看完成情况。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_profile_complete
from app.db import get_db
from app.models import (
    ROLE_DOCTOR,
    STATUS_IN_PROGRESS,
    STATUS_SUBMITTED,
    Answer,
    Attempt,
    Question,
    Task,
    User,
)
from app.schemas import (
    AnswerInput,
    AnswerSnapshot,
    AttemptCreate,
    AttemptHistoryItem,
    AttemptInProgress,
    AttemptResult,
)
from app.services.attempt_views import (
    build_attempt_history_items,
    build_in_progress_view,
    build_result_view,
)
from app.services.scoring import IncompleteAttemptError, submit_attempt

attempts_router = APIRouter(prefix="/api/attempts", tags=["attempts"])


def _published_task_or_404(db: Session, task_code: str, user: User) -> Task:
    task = db.scalar(select(Task).where(Task.code == task_code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if user.role == ROLE_DOCTOR and not task.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return task


def _own_attempt_or_404(db: Session, attempt_id: int, user: User) -> Attempt:
    a = db.get(Attempt, attempt_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "答题记录不存在")
    if a.user_id != user.id:
        # 即便是 admin 也不能从 doctor 端口干预（admin 后台另有路径）
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该答题记录")
    return a


def _batch_exists(db: Session, task_id: int, batch_index: int) -> bool:
    return bool(
        db.scalar(
            select(func.count(Question.id)).where(
                Question.task_id == task_id,
                Question.batch_index == batch_index,
                Question.is_deleted == 0,
            )
        )
    )


@attempts_router.post("", response_model=AttemptInProgress, status_code=status.HTTP_201_CREATED)
def create_or_resume_attempt(
    payload: AttemptCreate,
    user: User = Depends(require_profile_complete),
    db: Session = Depends(get_db),
) -> AttemptInProgress:
    task = _published_task_or_404(db, payload.task_code, user)
    batch_index = int(payload.batch_index or 0)
    if not _batch_exists(db, task.id, batch_index):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该批次不存在或暂无题目")

    # 检查是否有 in_progress 的 attempt → 续答
    existing = db.scalar(
        select(Attempt).where(
            Attempt.user_id == user.id,
            Attempt.task_id == task.id,
            Attempt.batch_index == batch_index,
            Attempt.status == STATUS_IN_PROGRESS,
        )
    )
    if existing is None:
        existing = Attempt(
            user_id=user.id,
            task_id=task.id,
            batch_index=batch_index,
            status=STATUS_IN_PROGRESS,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

    return build_in_progress_view(db, existing, task)


@attempts_router.get("/{attempt_id}", response_model=AttemptInProgress)
def get_attempt(
    attempt_id: int,
    user: User = Depends(require_profile_complete),
    db: Session = Depends(get_db),
) -> AttemptInProgress:
    a = _own_attempt_or_404(db, attempt_id, user)
    if a.status != STATUS_IN_PROGRESS:
        raise HTTPException(status.HTTP_409_CONFLICT, "该答题已提交，请到完成情况页查看")
    task = db.get(Task, a.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return build_in_progress_view(db, a, task)


@attempts_router.put("/{attempt_id}/answers/{question_id}", response_model=AnswerSnapshot)
def upsert_answer(
    attempt_id: int,
    question_id: int,
    payload: AnswerInput,
    user: User = Depends(require_profile_complete),
    db: Session = Depends(get_db),
) -> AnswerSnapshot:
    attempt = _own_attempt_or_404(db, attempt_id, user)
    if attempt.status != STATUS_IN_PROGRESS:
        raise HTTPException(status.HTTP_409_CONFLICT, "该答题已提交，无法再修改")

    question = db.get(Question, question_id)
    if (
        question is None
        or question.is_deleted
        or question.task_id != attempt.task_id
        or question.batch_index != attempt.batch_index
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")

    # 校验答案在 task.answer_options 中（允许空字符串表示未答）
    if payload.answer_text:
        task = db.get(Task, attempt.task_id)
        if payload.answer_text not in set(task.answer_options):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "答案不在选项列表里")

    existing = db.scalar(
        select(Answer).where(Answer.attempt_id == attempt.id, Answer.question_id == question.id)
    )
    now = datetime.utcnow()
    if existing is None:
        existing = Answer(
            attempt_id=attempt.id,
            question_id=question.id,
            answer_text=payload.answer_text,
            note=payload.note,
            review_flag=1 if payload.review_flag else 0,
            time_spent_seconds=payload.time_spent_seconds,
            updated_at=now,
        )
        db.add(existing)
    else:
        existing.answer_text = payload.answer_text
        existing.note = payload.note
        existing.review_flag = 1 if payload.review_flag else 0
        existing.time_spent_seconds = max(
            existing.time_spent_seconds or 0,
            payload.time_spent_seconds,
        )
        existing.updated_at = now

    attempt.updated_at = now
    db.commit()
    db.refresh(existing)
    return AnswerSnapshot(
        question_id=existing.question_id,
        answer_text=existing.answer_text,
        note=existing.note,
        review_flag=bool(existing.review_flag),
        time_spent_seconds=existing.time_spent_seconds,
        updated_at=existing.updated_at,
    )


@attempts_router.post("/{attempt_id}/submit", response_model=AttemptResult)
def submit(
    attempt_id: int,
    user: User = Depends(require_profile_complete),
    db: Session = Depends(get_db),
) -> AttemptResult:
    attempt = _own_attempt_or_404(db, attempt_id, user)
    if attempt.status == STATUS_SUBMITTED:
        # 幂等：已提交直接返回结果
        return build_result_view(db, attempt)
    try:
        submit_attempt(db, attempt)
    except IncompleteAttemptError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return build_result_view(db, attempt)


@attempts_router.get("/{attempt_id}/result", response_model=AttemptResult)
def get_result(
    attempt_id: int,
    user: User = Depends(require_profile_complete),
    db: Session = Depends(get_db),
) -> AttemptResult:
    attempt = _own_attempt_or_404(db, attempt_id, user)
    if attempt.status != STATUS_SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "该答题未提交")
    return build_result_view(db, attempt)


@attempts_router.get("", response_model=list[AttemptHistoryItem])
def my_attempts(
    user: User = Depends(require_profile_complete),
    db: Session = Depends(get_db),
) -> list[AttemptHistoryItem]:
    """医生看自己的答题历史。"""
    rows = list(
        db.scalars(
            select(Attempt).where(Attempt.user_id == user.id).order_by(Attempt.started_at.desc())
        ).all()
    )
    return build_attempt_history_items(db, rows)
