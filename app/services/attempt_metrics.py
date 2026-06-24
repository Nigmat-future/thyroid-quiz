"""Attempt-level accuracy and ROC/AUC metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

from app.services.fna import (
    is_answer_correct,
    is_uncertain_answer,
    malignancy_score_for,
    predicted_binary_for,
    truth_binary_for,
)


@dataclass(frozen=True, slots=True)
class AnswerMetricRow:
    answer_text: str
    ground_truth: str


@dataclass(frozen=True, slots=True)
class AucPoint:
    truth_binary: int
    malignancy_score: float


@dataclass(frozen=True, slots=True)
class AttemptMetrics:
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


def calculate_auc(points: Sequence[AucPoint]) -> float | None:
    """Calculate AUC from binary truth and configured malignancy risk scores."""
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
    """Summarize binary-direction accuracy and FNA AUC inputs for an attempt."""
    total = len(rows)
    answered_rows = [row for row in rows if row.answer_text]
    answered = len(answered_rows)
    correct = sum(
        1 for row in answered_rows if is_answer_correct(row.answer_text, row.ground_truth)
    )
    auc_points = [
        AucPoint(truth_binary=truth_binary, malignancy_score=malignancy_score)
        for row in rows
        if (truth_binary := truth_binary_for(row.ground_truth)) is not None
        and (malignancy_score := malignancy_score_for(row.answer_text)) is not None
    ]
    positive_count = sum(1 for point in auc_points if point.truth_binary == 1)
    negative_count = sum(1 for point in auc_points if point.truth_binary == 0)
    true_positive = 0
    true_negative = 0
    false_positive = 0
    false_negative = 0
    uncertain = 0
    for row in answered_rows:
        truth_binary = truth_binary_for(row.ground_truth)
        if truth_binary is None:
            continue
        if is_uncertain_answer(row.answer_text):
            uncertain += 1
            continue
        predicted_binary = predicted_binary_for(row.answer_text)
        if predicted_binary is None:
            continue
        outcome = (truth_binary, predicted_binary)
        match outcome:
            case (0, 0):
                true_negative += 1
            case (0, 1):
                false_positive += 1
            case (1, 0):
                false_negative += 1
            case (1, 1):
                true_positive += 1
            case unreachable:
                assert_never(unreachable)

    positive_predictions = true_positive + false_positive
    negative_predictions = true_negative + false_negative
    positive_truths = true_positive + false_negative
    negative_truths = true_negative + false_positive
    return AttemptMetrics(
        total=total,
        answered=answered,
        correct=correct,
        accuracy=(correct / answered) if answered else None,
        auc=calculate_auc(auc_points),
        auc_positive=positive_count,
        auc_negative=negative_count,
        uncertain=uncertain,
        ppv=(true_positive / positive_predictions) if positive_predictions else None,
        npv=(true_negative / negative_predictions) if negative_predictions else None,
        sensitivity=(true_positive / positive_truths) if positive_truths else None,
        specificity=(true_negative / negative_truths) if negative_truths else None,
    )
