"""CSV 导出。两种粒度：attempts 总览 + answers 逐题展开。"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Answer, Attempt, Question, Task, User
from app.services.attempt_metrics import AnswerMetricRow, summarize_attempt_metrics
from app.services.fna import (
    is_answer_correct,
    malignancy_score_for,
    parse_source_note,
    truth_binary_for,
)

# UTF-8 with BOM 让 Excel 直接打开不乱码
_BOM = "﻿"


def _writer(buf: io.StringIO) -> csv.writer:
    return csv.writer(buf, dialect="excel")


def _metric_rows_for_attempt(db: Session, attempt: Attempt) -> list[AnswerMetricRow]:
    questions = db.scalars(
        select(Question)
        .where(
            Question.task_id == attempt.task_id,
            Question.batch_index == attempt.batch_index,
            Question.is_deleted == 0,
        )
        .order_by(Question.batch_position, Question.order_index, Question.id)
    ).all()
    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt.id)).all()
    answers_by_question = {answer.question_id: answer.answer_text for answer in answers}
    return [
        AnswerMetricRow(
            answer_text=answers_by_question.get(question.id, ""),
            ground_truth=question.ground_truth,
        )
        for question in questions
    ]


def stream_attempts_csv(db: Session) -> Iterator[bytes]:
    """每行一个 attempt 的总览（含医生、任务、得分）。"""
    yield _BOM.encode("utf-8")
    buf = io.StringIO()
    w = _writer(buf)
    w.writerow([
        "attempt_id", "user_id", "username", "display_name",
        "task_code", "task_name", "status",
        "batch_index",
        "total", "correct", "score",
        "started_at", "submitted_at",
    ])
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    rows = db.execute(
        select(Attempt, User, Task)
        .join(User, Attempt.user_id == User.id)
        .join(Task, Attempt.task_id == Task.id)
        .order_by(Attempt.started_at.desc())
    ).all()

    for a, u, t in rows:
        metrics = summarize_attempt_metrics(_metric_rows_for_attempt(db, a))
        w.writerow([
            a.id, u.id, u.username, u.display_name or "",
            t.code, t.name, a.status,
            a.batch_index,
            metrics.total,
            metrics.correct,
            f"{metrics.accuracy:.4f}" if metrics.accuracy is not None else "",
            a.started_at.isoformat(sep=" ", timespec="seconds") if a.started_at else "",
            a.submitted_at.isoformat(sep=" ", timespec="seconds") if a.submitted_at else "",
        ])
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)


def stream_answers_csv(db: Session) -> Iterator[bytes]:
    """逐题展开：每行一题一答（仅已提交的 attempt）。"""
    yield _BOM.encode("utf-8")
    buf = io.StringIO()
    w = _writer(buf)
    w.writerow([
        "attempt_id", "username", "display_name",
        "task_code", "task_name",
        "question_id", "order_index", "batch_index", "batch_position",
        "answer_text", "ground_truth", "is_correct",
        "truth_binary", "doctor_malignancy_score",
        "review_flag", "time_spent_seconds",
        "source_center", "source_file_path",
        "note", "submitted_at",
    ])
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate(0)

    rows = db.execute(
        select(Answer, Attempt, User, Task, Question)
        .join(Attempt, Answer.attempt_id == Attempt.id)
        .join(User, Attempt.user_id == User.id)
        .join(Task, Attempt.task_id == Task.id)
        .join(Question, Answer.question_id == Question.id)
        .where(Attempt.status == "submitted")
        .order_by(Attempt.id.desc(), Question.order_index)
    ).all()

    for ans, a, u, t, q in rows:
        source_center, source_file_path = parse_source_note(q.note)
        truth_binary = truth_binary_for(q.ground_truth)
        malignancy_score = malignancy_score_for(ans.answer_text)
        w.writerow([
            a.id, u.username, u.display_name or "",
            t.code, t.name,
            q.id, q.order_index, q.batch_index, q.batch_position,
            ans.answer_text, q.ground_truth,
            1 if is_answer_correct(ans.answer_text, q.ground_truth) else 0,
            truth_binary if truth_binary is not None else "",
            malignancy_score if malignancy_score is not None else "",
            1 if ans.review_flag else 0,
            ans.time_spent_seconds,
            source_center,
            source_file_path,
            ans.note or "",
            a.submitted_at.isoformat(sep=" ", timespec="seconds") if a.submitted_at else "",
        ])
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate(0)
