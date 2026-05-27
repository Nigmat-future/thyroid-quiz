"""batches, review flags, per-question time

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("batch_index", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "questions", sa.Column("batch_position", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("attempts", sa.Column("batch_index", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("answers", sa.Column("review_flag", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "answers",
        sa.Column("time_spent_seconds", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("answers", "time_spent_seconds")
    op.drop_column("answers", "review_flag")
    op.drop_column("attempts", "batch_index")
    op.drop_column("questions", "batch_position")
    op.drop_column("questions", "batch_index")
