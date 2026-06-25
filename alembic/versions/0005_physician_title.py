"""physician title on users

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("physician_title", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "physician_title")
