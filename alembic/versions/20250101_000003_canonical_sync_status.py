"""Adopt canonical sync status lifecycle and add message column.

Revision ID: 20250101_000003
Revises: 20250101_000002
Create Date: 2025-01-01 00:00:03.000000
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from app.api.sync_lifecycle import migrate_legacy_statuses

# revision identifiers, used by Alembic.
revision: str = "20250101_000003"
down_revision: Union[str, None] = "20250101_000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add message column to runs if missing
    inspector = sa.inspect(conn)
    existing_columns = [col["name"] for col in inspector.get_columns("runs")]
    if "message" not in existing_columns:
        with op.batch_alter_table("runs") as batch_op:
            batch_op.add_column(sa.Column("message", sa.Text(), nullable=True))

    # 2. Inspect and migrate all existing statuses
    migrate_legacy_statuses(conn)


def downgrade() -> None:
    conn = op.get_bind()
    # Revert canonical back to legacy
    conn.execute(text("UPDATE runs SET status = 'success' WHERE status = 'completed'"))
    conn.execute(text("UPDATE runs SET status = 'stopped' WHERE status = 'aborted'"))
    conn.execute(text("UPDATE runs SET status = 'error' WHERE status IN ('failed', 'skipped', 'pending')"))

    inspector = sa.inspect(conn)
    existing_columns = [col["name"] for col in inspector.get_columns("runs")]
    if "message" in existing_columns:
        with op.batch_alter_table("runs") as batch_op:
            batch_op.drop_column("message")
