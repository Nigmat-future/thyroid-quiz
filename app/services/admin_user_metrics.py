"""Admin-facing aggregated metrics per user."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import STATUS_SUBMITTED, Answer, Attempt, Question, User
from app.services.attempt_metrics import AnswerMetricRow, summarize_attempt_metrics


@dataclass(frozen=True, slots=True)
class AdminUserMetricsSummary:
    submitted_attempts: int
    total: int
    answered: int
    correct: int
    accuracy: float | None
    auc: float | None
    auc_positive: int
    auc_negative: int


def _metric_rows_by_attempt_id(
    db: Session,
    attempts: Sequence[Attempt],
) -> dict[int, list[AnswerMetricRow]]:
    attempt_ids = [attempt.id for attempt in attempts]
    if not attempt_ids:
        return {}

    answer_rows = db.execute(
        select(Answer.attempt_id, Answer.question_id, Answer.answer_text).where(
            Answer.attempt_id.in_(attempt_ids)
        )
    ).all()
    answer_text_by_attempt_question = {
        (attempt_id, question_id): answer_text
        for attempt_id, question_id, answer_text in answer_rows
    }
    question_rows = db.execute(
        select(Attempt.id, Question.id, Question.ground_truth)
        .join(
            Question,
            and_(
                Question.task_id == Attempt.task_id,
                Question.batch_index == Attempt.batch_index,
                Question.is_deleted == 0,
            ),
        )
        .where(Attempt.id.in_(attempt_ids))
        .order_by(Attempt.id, Question.batch_position, Question.order_index, Question.id)
    ).all()

    rows_by_attempt_id: dict[int, list[AnswerMetricRow]] = {}
    for attempt_id, question_id, ground_truth in question_rows:
        rows_by_attempt_id.setdefault(attempt_id, []).append(
            AnswerMetricRow(
                answer_text=answer_text_by_attempt_question.get((attempt_id, question_id), ""),
                ground_truth=ground_truth,
            )
        )
    return rows_by_attempt_id


def summarize_users_metrics(
    db: Session,
    users: Sequence[User],
) -> dict[int, AdminUserMetricsSummary]:
    user_ids = [user.id for user in users]
    if not user_ids:
        return {}

    attempts = list(
        db.scalars(
            select(Attempt)
            .where(
                Attempt.user_id.in_(user_ids),
                Attempt.status == STATUS_SUBMITTED,
            )
            .order_by(Attempt.user_id, Attempt.id)
        ).all()
    )
    rows_by_attempt_id = _metric_rows_by_attempt_id(db, attempts)
    submitted_attempts_by_user_id: dict[int, int] = {}
    metric_rows_by_user_id: dict[int, list[AnswerMetricRow]] = {}
    for attempt in attempts:
        submitted_attempts_by_user_id[attempt.user_id] = (
            submitted_attempts_by_user_id.get(attempt.user_id, 0) + 1
        )
        metric_rows_by_user_id.setdefault(attempt.user_id, []).extend(
            rows_by_attempt_id.get(attempt.id, [])
        )

    summaries: dict[int, AdminUserMetricsSummary] = {}
    for user in users:
        metrics = summarize_attempt_metrics(metric_rows_by_user_id.get(user.id, []))
        summaries[user.id] = AdminUserMetricsSummary(
            submitted_attempts=submitted_attempts_by_user_id.get(user.id, 0),
            total=metrics.total,
            answered=metrics.answered,
            correct=metrics.correct,
            accuracy=metrics.accuracy,
            auc=metrics.auc,
            auc_positive=metrics.auc_positive,
            auc_negative=metrics.auc_negative,
        )
    return summaries
