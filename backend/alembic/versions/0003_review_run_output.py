"""review_runs: persist findings/summary/risk_level, and a source column

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_runs", sa.Column("source", sa.String(16), nullable=False, server_default="webhook")
    )
    op.add_column("review_runs", sa.Column("findings", postgresql.JSONB(), nullable=True))
    op.add_column("review_runs", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("review_runs", sa.Column("risk_level", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("review_runs", "risk_level")
    op.drop_column("review_runs", "summary")
    op.drop_column("review_runs", "findings")
    op.drop_column("review_runs", "source")
