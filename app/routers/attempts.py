"""答题 API：创建/续答 attempt、保存单题、提交、查看结果。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
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
    AttemptInProgress,
    AttemptResult,
    AttemptResultRow,
)
from app.services.scoring import submit_attempt
from app.services.storage import public_url_of

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


def _questions_of_task(db: Session, task_id: int) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .where(Question.task_id == task_id, Question.is_deleted == 0)
            .order_by(Question.order_index, Question.id)
        ).all()
    )


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


def _batch_total(db: Session, task_id: int) -> int:
    total = db.scalar(
        select(func.count(func.distinct(Question.batch_index))).where(
            Question.task_id == task_id,
            Question.is_deleted == 0,
        )
    )
    return int(total or 1)


@attempts_router.post("", response_model=AttemptInProgress, status_code=status.HTTP_201_CREATED)
def create_or_resume_attempt(
    payload: AttemptCreate,
    user: User = Depends(get_current_user),
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

    return _build_in_progress_view(db, existing, task)


@attempts_router.get("/{attempt_id}", response_model=AttemptInProgress)
def get_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttemptInProgress:
    a = _own_attempt_or_404(db, attempt_id, user)
    if a.status != STATUS_IN_PROGRESS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "该答题已提交，请到结果页查看"
        )
    task = db.get(Task, a.task_id)
    return _build_in_progress_view(db, a, task)


def _build_in_progress_view(db: Session, attempt: Attempt, task: Task) -> AttemptInProgress:
    questions = _questions_of_attempt(db, attempt)
    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt.id)).all()

    return AttemptInProgress(
        id=attempt.id,
        task_code=task.code,
        task_name=task.name,
        answer_options=task.answer_options,
        status=attempt.status,
        batch_index=attempt.batch_index,
        batch_total=_batch_total(db, task.id),
        started_at=attempt.started_at,
        updated_at=attempt.updated_at,
        questions=[
            {
                "id": q.id,
                "image_url": public_url_of(q.image_path),
                "order_index": q.order_index,
                "batch_index": q.batch_index,
                "batch_position": q.batch_position,
                "note": q.note,
            }
            for q in questions
        ],
        answers=[
            AnswerSnapshot(
                question_id=a.question_id,
                answer_text=a.answer_text,
                note=a.note,
                review_flag=bool(a.review_flag),
                time_spent_seconds=a.time_spent_seconds,
                updated_at=a.updated_at,
            )
            for a in answers
        ],
    )


@attempts_router.put("/{attempt_id}/answers/{question_id}", response_model=AnswerSnapshot)
def upsert_answer(
    attempt_id: int,
    question_id: int,
    payload: AnswerInput,
    user: User = Depends(get_current_user),
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
        select(Answer).where(
            Answer.attempt_id == attempt.id, Answer.question_id == question.id
        )
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttemptResult:
    attempt = _own_attempt_or_404(db, attempt_id, user)
    if attempt.status == STATUS_SUBMITTED:
        # 幂等：已提交直接返回结果
        return _build_result_view(db, attempt)
    submit_attempt(db, attempt)
    return _build_result_view(db, attempt)


@attempts_router.get("/{attempt_id}/result", response_model=AttemptResult)
def get_result(
    attempt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttemptResult:
    attempt = _own_attempt_or_404(db, attempt_id, user)
    if attempt.status != STATUS_SUBMITTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "该答题未提交")
    return _build_result_view(db, attempt)


def _build_result_view(db: Session, attempt: Attempt) -> AttemptResult:
    task = db.get(Task, attempt.task_id)
    questions = _questions_of_attempt(db, attempt)
    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt.id)).all()
    answer_map = {a.question_id: a for a in answers}

    rows: list[AttemptResultRow] = []
    for q in questions:
        a = answer_map.get(q.id)
        rows.append(
            AttemptResultRow(
                question_id=q.id,
                image_url=public_url_of(q.image_path),
                order_index=q.order_index,
                batch_index=q.batch_index,
                batch_position=q.batch_position,
                answer_text=a.answer_text if a else "",
                note=a.note if a else "",
                review_flag=bool(a and a.review_flag),
                time_spent_seconds=a.time_spent_seconds if a else 0,
                ground_truth=q.ground_truth,
                is_correct=bool(a and a.is_correct),
            )
        )

    return AttemptResult(
        id=attempt.id,
        task_code=task.code,
        task_name=task.name,
        status=attempt.status,
        batch_index=attempt.batch_index,
        score=float(attempt.score or 0.0),
        total=int(attempt.total or 0),
        correct=int(attempt.correct or 0),
        submitted_at=attempt.submitted_at,
        rows=rows,
    )


@attempts_router.get("", response_model=list[dict])
def my_attempts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """医生看自己的答题历史。"""
    rows = db.scalars(
        select(Attempt).where(Attempt.user_id == user.id).order_by(Attempt.started_at.desc())
    ).all()
    out = []
    for a in rows:
        task = db.get(Task, a.task_id)
        out.append({
            "id": a.id,
            "task_code": task.code if task else "",
            "task_name": task.name if task else "(已删除)",
            "status": a.status,
            "batch_index": a.batch_index,
            "score": a.score,
            "correct": a.correct,
            "total": a.total,
            "started_at": a.started_at,
            "submitted_at": a.submitted_at,
        })
    return out
