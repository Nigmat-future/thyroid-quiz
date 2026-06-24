"""Admin attempt routes and filtered user summaries."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Answer, Attempt, Question, Task, User
from app.schemas_admin import (
    AdminAttemptDetail,
    AdminAttemptDetailRow,
    AdminAttemptDetailTask,
    AdminAttemptDetailUser,
    AdminAttemptUserSummary,
    AdminPerformanceMetrics,
    AttemptSummary,
)
from app.services.admin_user_metrics import summarize_attempt_groups
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

admin_attempts_router = APIRouter()


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


def _attempt_query(
    task_code: str | None,
    user_id: int | None,
    status_: str | None,
):
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
    return stmt.order_by(Attempt.started_at.desc())


@admin_attempts_router.get("/attempts", response_model=list[AttemptSummary])
def list_attempts(
    task_code: str | None = Query(None),
    user_id: int | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> list[AttemptSummary]:
    rows = db.execute(_attempt_query(task_code, user_id, status_)).all()
    out: list[AttemptSummary] = []
    for attempt, user, task in rows:
        questions = _questions_of_attempt(db, attempt)
        answers_by_question = _answer_map(db, attempt.id)
        metrics = summarize_attempt_metrics(_metric_rows(questions, answers_by_question))
        out.append(
            AttemptSummary(
                id=attempt.id,
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                task_id=task.id,
                task_code=task.code,
                task_name=task.name,
                status=attempt.status,
                batch_index=attempt.batch_index,
                score=metrics.accuracy,
                total=metrics.total,
                correct=metrics.correct,
                answered=metrics.answered,
                auc=metrics.auc,
                started_at=attempt.started_at,
                submitted_at=attempt.submitted_at,
            )
        )
    return out


@admin_attempts_router.get(
    "/attempts/user-summaries",
    response_model=list[AdminAttemptUserSummary],
)
def list_attempt_user_summaries(
    task_code: str | None = Query(None),
    user_id: int | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
) -> list[AdminAttemptUserSummary]:
    rows = db.execute(_attempt_query(task_code, user_id, status_)).all()
    attempts = [attempt for attempt, _user, _task in rows]
    users_by_id = {user.id: user for _attempt, user, _task in rows}
    summaries = summarize_attempt_groups(db, list(users_by_id.values()), attempts, attempts)
    return [
        AdminAttemptUserSummary(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            submitted_attempts=summaries[user.id].submitted_attempts,
            in_progress_attempts=summaries[user.id].in_progress_attempts,
            submitted_answered=summaries[user.id].submitted_answered,
            in_progress_answered=summaries[user.id].in_progress_answered,
            total=summaries[user.id].total,
            answered=summaries[user.id].answered,
            correct=summaries[user.id].correct,
            accuracy=summaries[user.id].accuracy,
            auc=summaries[user.id].auc,
            auc_positive=summaries[user.id].auc_positive,
            auc_negative=summaries[user.id].auc_negative,
            uncertain=summaries[user.id].uncertain,
            ppv=summaries[user.id].ppv,
            npv=summaries[user.id].npv,
            sensitivity=summaries[user.id].sensitivity,
            specificity=summaries[user.id].specificity,
        )
        for user in sorted(users_by_id.values(), key=lambda current_user: current_user.id)
    ]


@admin_attempts_router.get("/attempts/{attempt_id}", response_model=AdminAttemptDetail)
def get_attempt_detail(
    attempt_id: int, db: Session = Depends(get_db)
) -> AdminAttemptDetail:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "答题记录不存在")
    user = db.get(User, attempt.user_id)
    task = db.get(Task, attempt.task_id)
    questions = _questions_of_attempt(db, attempt)
    answers_by_question = _answer_map(db, attempt.id)
    metrics = summarize_attempt_metrics(_metric_rows(questions, answers_by_question))
    rows: list[AdminAttemptDetailRow] = []
    for question in questions:
        answer = answers_by_question.get(question.id)
        answer_text = answer.answer_text if answer else ""
        source_center, source_file_path = parse_source_note(question.note)
        rows.append(
            AdminAttemptDetailRow(
                question_id=question.id,
                order_index=question.order_index,
                batch_index=question.batch_index,
                batch_position=question.batch_position,
                image_url=public_url_of(question.image_path),
                ground_truth=question.ground_truth,
                answer_text=answer_text,
                note=answer.note if answer else "",
                review_flag=bool(answer and answer.review_flag),
                time_spent_seconds=answer.time_spent_seconds if answer else 0,
                is_correct=is_answer_correct(answer_text, question.ground_truth),
                truth_binary=truth_binary_for(question.ground_truth),
                doctor_malignancy_score=malignancy_score_for(answer_text),
                source_center=source_center,
                source_file_path=source_file_path,
            )
        )
    return AdminAttemptDetail(
        id=attempt.id,
        user=AdminAttemptDetailUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
        ),
        task=AdminAttemptDetailTask(id=task.id, code=task.code, name=task.name),
        status=attempt.status,
        batch_index=attempt.batch_index,
        score=metrics.accuracy,
        total=metrics.total,
        correct=metrics.correct,
        started_at=attempt.started_at,
        updated_at=attempt.updated_at,
        submitted_at=attempt.submitted_at,
        metrics=AdminPerformanceMetrics(
            total=metrics.total,
            answered=metrics.answered,
            correct=metrics.correct,
            accuracy=metrics.accuracy,
            auc=metrics.auc,
            auc_positive=metrics.auc_positive,
            auc_negative=metrics.auc_negative,
            uncertain=metrics.uncertain,
            ppv=metrics.ppv,
            npv=metrics.npv,
            sensitivity=metrics.sensitivity,
            specificity=metrics.specificity,
        ),
        rows=rows,
    )


def _csv_response(stream, filename: str) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@admin_attempts_router.get("/exports/attempts.csv")
def export_attempts_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    filename = f"attempts_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return _csv_response(stream_attempts_csv(db), filename)


@admin_attempts_router.get("/exports/answers.csv")
def export_answers_csv(db: Session = Depends(get_db)) -> StreamingResponse:
    filename = f"answers_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return _csv_response(stream_answers_csv(db), filename)
