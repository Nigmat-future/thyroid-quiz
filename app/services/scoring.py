"""答题计分。提交时一次性回填 is_correct 与 attempt 的总分。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    STATUS_IN_PROGRESS,
    STATUS_SUBMITTED,
    Answer,
    Attempt,
    Question,
)
from app.services.fna import is_answer_correct


class IncompleteAttemptError(ValueError):
    """提交时仍有题目未作答。"""

    def __init__(self, unanswered: int, total: int) -> None:
        self.unanswered = unanswered
        self.total = total
        super().__init__(f"还有 {unanswered} / {total} 题未作答，请完成全部题目后再提交")


def submit_attempt(db: Session, attempt: Attempt) -> Attempt:
    """对 attempt 计分并锁定。已提交的不重复处理。"""
    if attempt.status == STATUS_SUBMITTED:
        return attempt
    if attempt.status != STATUS_IN_PROGRESS:
        raise ValueError(f"attempt 状态非法：{attempt.status}")

    # 取所有未删的题目（按当前 task）
    questions = db.scalars(
        select(Question)
        .where(
            Question.task_id == attempt.task_id,
            Question.batch_index == attempt.batch_index,
            Question.is_deleted == 0,
        )
        .order_by(Question.batch_position, Question.order_index, Question.id)
    ).all()
    qmap = {q.id: q for q in questions}
    total = len(questions)

    answers = db.scalars(select(Answer).where(Answer.attempt_id == attempt.id)).all()
    answers_by_question = {a.question_id: a for a in answers}
    unanswered = sum(
        1
        for q in questions
        if not (answers_by_question.get(q.id) and answers_by_question[q.id].answer_text.strip())
    )
    if unanswered:
        raise IncompleteAttemptError(unanswered=unanswered, total=total)

    correct = 0
    for a in answers:
        q = qmap.get(a.question_id)
        if q is None:
            # 题目被软删了；不计入正确数也不报错
            a.is_correct = 0
            continue
        a.is_correct = 1 if is_answer_correct(a.answer_text, q.ground_truth) else 0
        if a.is_correct:
            correct += 1

    attempt.total = total
    attempt.correct = correct
    attempt.score = (correct / total) if total > 0 else 0.0
    attempt.status = STATUS_SUBMITTED
    attempt.submitted_at = datetime.utcnow()
    attempt.updated_at = attempt.submitted_at
    db.commit()
    db.refresh(attempt)
    return attempt
