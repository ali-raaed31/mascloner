"""Seed durable schedule settings (enabled, interval, jitter) in SQLite.

Revision ID: 20250101_000002
Revises: 20250101_000001
Create Date: 2025-01-01 00:00:02
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250101_000002"
down_revision: Union[str, None] = "20250101_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Inspect existing keys
    existing_keys = set()
    result = conn.execute(sa.text("SELECT key FROM config"))
    for row in result:
        existing_keys.add(row[0])

    # 2. Read environment fallback values (including from .env if base dir or env file is set)
    env_vars = dict(os.environ)
    env_file_path = None
    if "MASCLONER_ENV_FILE" in os.environ:
        env_file_path = Path(os.environ["MASCLONER_ENV_FILE"])
    elif "MASCLONER_BASE_DIR" in os.environ:
        env_file_path = Path(os.environ["MASCLONER_BASE_DIR"]) / ".env"

    if env_file_path and env_file_path.exists():
        try:
            for line in env_file_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    env_vars[k] = v
        except Exception:
            pass

    # Map of (setting_key, env_var_name, default_value)
    # ADR 0007: Existing installations migrate with enabled=true so an update preserves scheduling behavior.
    settings_to_seed = [
        ("schedule_enabled", None, "true"),
        ("interval_min", "SYNC_INTERVAL_MIN", "5"),
        ("jitter_sec", "SYNC_JITTER_SEC", "20"),
    ]

    inserts = []
    for key, env_key, default_val in settings_to_seed:
        if key not in existing_keys:
            if env_key and env_key in env_vars and env_vars[env_key] != "":
                val = env_vars[env_key]
                prov = "imported_legacy"
            else:
                val = default_val
                prov = "default"

            inserts.append({
                "key": key,
                "value": str(val),
                "provenance": prov,
            })

    for item in inserts:
        conn.execute(
            sa.text(
                "INSERT INTO config (key, value, provenance, updated_at) "
                "VALUES (:key, :value, :provenance, CURRENT_TIMESTAMP)"
            ),
            item,
        )


def downgrade() -> None:
    conn = op.get_bind()
    schedule_keys = ["schedule_enabled", "interval_min", "jitter_sec"]
    for key in schedule_keys:
        conn.execute(sa.text("DELETE FROM config WHERE key = :key"), {"key": key})
