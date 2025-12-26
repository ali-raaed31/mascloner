"""Initial schema matching existing models.

Revision ID: 20241224_000001
Revises: 
Create Date: 2024-12-24 00:00:01

This migration creates the initial database schema matching the existing
SQLAlchemy models. This is the baseline migration for existing databases.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20241224_000001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial tables."""
    # Config table
    op.create_table(
        "config",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # Runs table
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("num_added", sa.Integer(), default=0, nullable=False),
        sa.Column("num_updated", sa.Integer(), default=0, nullable=False),
        sa.Column("bytes_transferred", sa.BigInteger(), default=0, nullable=False),
        sa.Column("errors", sa.Integer(), default=0, nullable=False),
        sa.Column("log_path", sa.Text(), nullable=True),
    )
    op.create_index("idx_runs_started_at", "runs", ["started_at"])

    # File events table
    op.create_table(
        "file_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), default=0, nullable=False),
        sa.Column("file_hash", sa.String(128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
    )
    op.create_index("idx_file_events_run_id", "file_events", ["run_id"])
    op.create_index("idx_file_events_timestamp", "file_events", ["timestamp"])
    op.create_index("idx_file_events_action", "file_events", ["action"])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index("idx_file_events_action", "file_events")
    op.drop_index("idx_file_events_timestamp", "file_events")
    op.drop_index("idx_file_events_run_id", "file_events")
    op.drop_table("file_events")

    op.drop_index("idx_runs_started_at", "runs")
    op.drop_table("runs")

    op.drop_table("config")

