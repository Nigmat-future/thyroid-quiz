"""Doctor-facing attempt view builders."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Answer, Attempt, Question, Task
from app.schemas import (
    AnswerSnapshot,
    AttemptHistoryItem,
    AttemptInProgress,
    AttemptResult,
    AttemptResultRow,
)
from app.services.storage import public_url_of


def questions_of_attempt(db: Session, attempt: Attempt) -> list[Question]:
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


def batch_total(db: Session, task_id: int) -> int:
    total = db.scalar(
        select(func.count(func.distinct(Question.batch_index))).where(
            Question.task_id == task_id,
            Question.is_deleted == 0,
        )
    )
    return int(total or 1)


def _question_total(db: Session, attempt: Attempt) -> int:
    total = db.scalar(
        select(func.count(Question.id)).where(
            Question.task_id == attempt.task_id,
            Question.batch_index == attempt.batch_index,
            Question.is_deleted == 0,
        )
    )
    return int(total or 0)


def _answered_total(db: Session, attempt: Attempt) -> int:
    answered = db.scalar(
        select(func.count(Answer.id)).where(
            Answer.attempt_id == attempt.id,
            Answer.answer_text != "",
        )
    )
    return int(answered or 0)


def build_in_progress_view(db: Session, attempt: Attempt, task: Task) -> AttemptInProgress:
    questions = questions_of_attempt(db, attempt)
    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt.id)).all()

    return AttemptInProgress(
        id=attempt.id,
        task_code=task.code,
        task_name=task.name,
        answer_options=task.answer_options,
        status=attempt.status,
        batch_index=attempt.batch_index,
        batch_total=batch_total(db, task.id),
        started_at=attempt.started_at,
        updated_at=attempt.updated_at,
        questions=[
            {
                "id": question.id,
                "image_url": public_url_of(question.image_path),
                "order_index": question.order_index,
                "batch_index": question.batch_index,
                "batch_position": question.batch_position,
                "note": question.note,
            }
            for question in questions
        ],
        answers=[
            AnswerSnapshot(
                question_id=answer.question_id,
                answer_text=answer.answer_text,
                note=answer.note,
                review_flag=bool(answer.review_flag),
                time_spent_seconds=answer.time_spent_seconds,
                updated_at=answer.updated_at,
            )
            for answer in answers
        ],
    )


def build_result_view(db: Session, attempt: Attempt) -> AttemptResult:
    task = db.get(Task, attempt.task_id)
    questions = questions_of_attempt(db, attempt)
    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt.id)).all()
    answer_map = {answer.question_id: answer for answer in answers}

    rows: list[AttemptResultRow] = []
    for question in questions:
        answer = answer_map.get(question.id)
        rows.append(
            AttemptResultRow(
                question_id=question.id,
                image_url=public_url_of(question.image_path),
                order_index=question.order_index,
                batch_index=question.batch_index,
                batch_position=question.batch_position,
                answer_text=answer.answer_text if answer else "",
                note=answer.note if answer else "",
                review_flag=bool(answer and answer.review_flag),
                time_spent_seconds=answer.time_spent_seconds if answer else 0,
            )
        )

    return AttemptResult(
        id=attempt.id,
        task_code=task.code if task else "",
        task_name=task.name if task else "(已删除)",
        status=attempt.status,
        batch_index=attempt.batch_index,
        total=len(rows),
        answered=sum(1 for row in rows if row.answer_text),
        submitted_at=attempt.submitted_at or attempt.updated_at,
        rows=rows,
    )


def build_attempt_history_items(db: Session, attempts: list[Attempt]) -> list[AttemptHistoryItem]:
    items: list[AttemptHistoryItem] = []
    for attempt in attempts:
        task = db.get(Task, attempt.task_id)
        items.append(
            AttemptHistoryItem(
                id=attempt.id,
                task_code=task.code if task else "",
                task_name=task.name if task else "(已删除)",
                status=attempt.status,
                batch_index=attempt.batch_index,
                batch_total=batch_total(db, task.id) if task else 1,
                answered=_answered_total(db, attempt),
                total=_question_total(db, attempt),
                started_at=attempt.started_at,
                submitted_at=attempt.submitted_at,
            )
        )
    return items
