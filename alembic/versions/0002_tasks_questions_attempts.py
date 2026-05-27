"""tasks / questions / attempts / answers

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("answer_options_json", sa.Text, nullable=False),
        sa.Column("randomize_options", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_published", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
    )
    op.create_index("ix_tasks_code", "tasks", ["code"], unique=True)
    op.create_index("ix_tasks_created_by", "tasks", ["created_by"])

    op.create_table(
        "questions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("image_path", sa.String(255), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("ground_truth", sa.String(64), nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("uploaded_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_deleted", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
    )
    op.create_index("ix_questions_task_id", "questions", ["task_id"])
    op.create_index("ix_questions_image_sha256", "questions", ["image_sha256"])

    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_id", sa.Integer, sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column("score", sa.Float, nullable=True),
        sa.Column("total", sa.Integer, nullable=True),
        sa.Column("correct", sa.Integer, nullable=True),
        sa.Column(
            "started_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_attempts_user_id", "attempts", ["user_id"])
    op.create_index("ix_attempts_task_id", "attempts", ["task_id"])

    op.create_table(
        "answers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "attempt_id",
            sa.Integer,
            sa.ForeignKey("attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("answer_text", sa.Text, nullable=False, server_default=""),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("is_correct", sa.Integer, nullable=True),
        sa.Column(
            "updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_q"),
    )
    op.create_index("ix_answers_attempt_id", "answers", ["attempt_id"])


def downgrade() -> None:
    op.drop_index("ix_answers_attempt_id", "answers")
    op.drop_table("answers")
    op.drop_index("ix_attempts_task_id", "attempts")
    op.drop_index("ix_attempts_user_id", "attempts")
    op.drop_table("attempts")
    op.drop_index("ix_questions_image_sha256", "questions")
    op.drop_index("ix_questions_task_id", "questions")
    op.drop_table("questions")
    op.drop_index("ix_tasks_created_by", "tasks")
    op.drop_index("ix_tasks_code", "tasks")
    op.drop_table("tasks")
