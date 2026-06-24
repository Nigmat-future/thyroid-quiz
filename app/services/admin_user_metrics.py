"""Admin-facing aggregated metrics per user."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import STATUS_IN_PROGRESS, STATUS_SUBMITTED, Answer, Attempt, Question, User
from app.services.attempt_metrics import AnswerMetricRow, summarize_attempt_metrics


@dataclass(frozen=True, slots=True)
class AdminUserMetricsSummary:
    submitted_attempts: int
    in_progress_attempts: int
    submitted_answered: int
    in_progress_answered: int
    total: int
    answered: int
    correct: int
    accuracy: float | None
    auc: float | None
    auc_positive: int
    auc_negative: int
    uncertain: int
    ppv: float | None
    npv: float | None
    sensitivity: float | None
    specificity: float | None


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


def _answered_counts_by_attempt_id(
    db: Session,
    attempts: Sequence[Attempt],
) -> dict[int, int]:
    attempt_ids = [attempt.id for attempt in attempts]
    if not attempt_ids:
        return {}

    rows = db.execute(
        select(Answer.attempt_id, func.count(Answer.id))
        .where(
            Answer.attempt_id.in_(attempt_ids),
            Answer.answer_text != "",
        )
        .group_by(Answer.attempt_id)
    ).all()
    return {attempt_id: int(answered_count) for attempt_id, answered_count in rows}


def summarize_attempt_groups(
    db: Session,
    users: Sequence[User],
    metric_attempts: Sequence[Attempt],
    progress_attempts: Sequence[Attempt],
) -> dict[int, AdminUserMetricsSummary]:
    """Summarize user performance from metric attempts and progress from all attempts."""
    answered_counts_by_attempt_id = _answered_counts_by_attempt_id(db, progress_attempts)
    rows_by_attempt_id = _metric_rows_by_attempt_id(db, metric_attempts)
    submitted_attempts_by_user_id: dict[int, int] = {}
    in_progress_attempts_by_user_id: dict[int, int] = {}
    submitted_answered_by_user_id: dict[int, int] = {}
    in_progress_answered_by_user_id: dict[int, int] = {}
    metric_rows_by_user_id: dict[int, list[AnswerMetricRow]] = {}

    for attempt in progress_attempts:
        answered_count = answered_counts_by_attempt_id.get(attempt.id, 0)
        if attempt.status == STATUS_SUBMITTED:
            submitted_attempts_by_user_id[attempt.user_id] = (
                submitted_attempts_by_user_id.get(attempt.user_id, 0) + 1
            )
            submitted_answered_by_user_id[attempt.user_id] = (
                submitted_answered_by_user_id.get(attempt.user_id, 0) + answered_count
            )
        elif attempt.status == STATUS_IN_PROGRESS:
            in_progress_attempts_by_user_id[attempt.user_id] = (
                in_progress_attempts_by_user_id.get(attempt.user_id, 0) + 1
            )
            in_progress_answered_by_user_id[attempt.user_id] = (
                in_progress_answered_by_user_id.get(attempt.user_id, 0) + answered_count
            )

    for attempt in metric_attempts:
        metric_rows_by_user_id.setdefault(attempt.user_id, []).extend(
            rows_by_attempt_id.get(attempt.id, [])
        )

    summaries: dict[int, AdminUserMetricsSummary] = {}
    for user in users:
        metrics = summarize_attempt_metrics(metric_rows_by_user_id.get(user.id, []))
        summaries[user.id] = AdminUserMetricsSummary(
            submitted_attempts=submitted_attempts_by_user_id.get(user.id, 0),
            in_progress_attempts=in_progress_attempts_by_user_id.get(user.id, 0),
            submitted_answered=submitted_answered_by_user_id.get(user.id, 0),
            in_progress_answered=in_progress_answered_by_user_id.get(user.id, 0),
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
        )
    return summaries


def summarize_users_metrics(
    db: Session,
    users: Sequence[User],
) -> dict[int, AdminUserMetricsSummary]:
    """Summarize submitted performance plus current progress for the given users."""
    user_ids = [user.id for user in users]
    if not user_ids:
        return {}

    progress_attempts = list(
        db.scalars(
            select(Attempt)
            .where(
                Attempt.user_id.in_(user_ids),
                Attempt.status.in_((STATUS_SUBMITTED, STATUS_IN_PROGRESS)),
            )
            .order_by(Attempt.user_id, Attempt.id)
        ).all()
    )
    metric_attempts = [
        attempt for attempt in progress_attempts if attempt.status == STATUS_SUBMITTED
    ]
    return summarize_attempt_groups(db, users, metric_attempts, progress_attempts)
