"""review_runs: idempotency tracking for the GitHub App webhook

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "done", "failed", "skipped", name="review_run_status"),
            nullable=False,
        ),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repository_id", "pr_number", "head_sha", name="uq_review_run_repo_pr_sha"),
    )
    op.create_index("ix_review_runs_repository_id", "review_runs", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_review_runs_repository_id", table_name="review_runs")
    op.drop_table("review_runs")
    op.execute("DROP TYPE IF EXISTS review_run_status")
