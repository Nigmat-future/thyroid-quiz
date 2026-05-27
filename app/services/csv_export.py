"""CSV 导出。两种粒度：attempts 总览 + answers 逐题展开。"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Answer, Attempt, Question, Task, User
from app.services.fna import (
    MALIGNANCY_SCORE_BY_ANSWER,
    TRUTH_BINARY_BY_GROUND_TRUTH,
    parse_source_note,
)

# UTF-8 with BOM 让 Excel 直接打开不乱码
_BOM = "﻿"


def _writer(buf: io.StringIO) -> csv.writer:
    return csv.writer(buf, dialect="excel")


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
        w.writerow([
            a.id, u.id, u.username, u.display_name or "",
            t.code, t.name, a.status,
            a.batch_index,
            a.total if a.total is not None else "",
            a.correct if a.correct is not None else "",
            f"{a.score:.4f}" if a.score is not None else "",
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
        truth_binary = TRUTH_BINARY_BY_GROUND_TRUTH.get(q.ground_truth)
        malignancy_score = MALIGNANCY_SCORE_BY_ANSWER.get(ans.answer_text)
        w.writerow([
            a.id, u.username, u.display_name or "",
            t.code, t.name,
            q.id, q.order_index, q.batch_index, q.batch_position,
            ans.answer_text, q.ground_truth,
            1 if ans.is_correct else 0,
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
