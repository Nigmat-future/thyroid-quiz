"""career_stage_other for custom identity

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("career_stage_other", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "career_stage_other")
