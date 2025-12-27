"""Add index on runs.status for live monitoring queries.

Revision ID: 20241226_000001
Revises: 20241224_000001
Create Date: 2024-12-26 00:00:01

This migration adds an index on the status column of the runs table
to optimize queries for the live sync monitoring feature, particularly
the query for finding running syncs.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20241226_000001"
down_revision: Union[str, None] = "20241224_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add index on runs.status column."""
    op.create_index("idx_runs_status", "runs", ["status"])


def downgrade() -> None:
    """Remove index on runs.status column."""
    op.drop_index("idx_runs_status", "runs")

