"""Canonical status lifecycle, transitions, and legacy migration logic."""

from __future__ import annotations

import logging
from typing import Set
from sqlalchemy import text
from sqlalchemy.engine import Engine, Connection

logger = logging.getLogger(__name__)

LEGACY_STATUS_MAP = {
    "success": "completed",
    "error": "failed",
    "partial": "failed",
    "stopped": "aborted",
    "cancelled": "aborted",
    "canceled": "aborted",
}

CANONICAL_STATUSES: Set[str] = {
    "pending",
    "running",
    "completed",
    "failed",
    "aborted",
    "skipped",
}


def migrate_legacy_statuses(target: Engine | Connection) -> None:
    """Migrate all runs records to canonical statuses.

    Fails safely if an unknown status is encountered.
    """
    is_engine = isinstance(target, Engine)
    conn = target.connect() if is_engine else target

    try:
        rows = conn.execute(text("SELECT DISTINCT status FROM runs")).fetchall()
        for row in rows:
            st = row[0]
            if not st:
                continue
            st_lower = str(st).lower()
            if st_lower in CANONICAL_STATUSES:
                continue
            if st_lower in LEGACY_STATUS_MAP:
                new_st = LEGACY_STATUS_MAP[st_lower]
                conn.execute(
                    text("UPDATE runs SET status = :new_st WHERE status = :old_st"),
                    {"new_st": new_st, "old_st": st},
                )
                logger.info("Migrated run status %r -> %r", st, new_st)
            else:
                raise ValueError(
                    f"Unknown legacy run status {st!r} encountered. Migration aborted safely."
                )
        if is_engine:
            conn.commit()
    finally:
        if is_engine:
            conn.close()
