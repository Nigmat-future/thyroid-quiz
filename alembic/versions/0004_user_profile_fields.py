"""user profile fields: hospital, career stage, license years

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("work_hospital", sa.String(256), nullable=True))
    op.add_column("users", sa.Column("career_stage", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("license_years", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "license_years")
    op.drop_column("users", "career_stage")
    op.drop_column("users", "work_hospital")
