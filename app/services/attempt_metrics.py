"""Attempt-level accuracy and ROC/AUC metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.fna import MALIGNANCY_SCORE_BY_ANSWER, TRUTH_BINARY_BY_GROUND_TRUTH


@dataclass(frozen=True, slots=True)
class AnswerMetricRow:
    answer_text: str
    ground_truth: str


@dataclass(frozen=True, slots=True)
class AucPoint:
    truth_binary: int
    malignancy_score: int


@dataclass(frozen=True, slots=True)
class AttemptMetrics:
    total: int
    answered: int
    correct: int
    accuracy: float | None
    auc: float | None
    auc_positive: int
    auc_negative: int


def truth_binary_for(ground_truth: str) -> int | None:
    """Return the binary truth used by FNA ROC/AUC exports."""
    return TRUTH_BINARY_BY_GROUND_TRUTH.get(ground_truth)


def malignancy_score_for(answer_text: str) -> int | None:
    """Return the ordinal malignancy score used by FNA ROC/AUC exports."""
    return MALIGNANCY_SCORE_BY_ANSWER.get(answer_text)


def calculate_auc(points: Sequence[AucPoint]) -> float | None:
    """Calculate AUC from binary truth and ordinal malignancy scores."""
    positives = [point.malignancy_score for point in points if point.truth_binary == 1]
    negatives = [point.malignancy_score for point in points if point.truth_binary == 0]
    if not positives or not negatives:
        return None

    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5

    return wins / (len(positives) * len(negatives))


def summarize_attempt_metrics(rows: Sequence[AnswerMetricRow]) -> AttemptMetrics:
    """Summarize exact-match accuracy and FNA AUC inputs for an attempt."""
    total = len(rows)
    answered = sum(1 for row in rows if row.answer_text)
    correct = sum(
        1 for row in rows if row.answer_text and row.answer_text == row.ground_truth
    )
    auc_points = [
        AucPoint(truth_binary=truth_binary, malignancy_score=malignancy_score)
        for row in rows
        if (truth_binary := truth_binary_for(row.ground_truth)) is not None
        and (malignancy_score := malignancy_score_for(row.answer_text)) is not None
    ]
    positive_count = sum(1 for point in auc_points if point.truth_binary == 1)
    negative_count = sum(1 for point in auc_points if point.truth_binary == 0)
    return AttemptMetrics(
        total=total,
        answered=answered,
        correct=correct,
        accuracy=(correct / total) if total else None,
        auc=calculate_auc(auc_points),
        auc_positive=positive_count,
        auc_negative=negative_count,
    )
