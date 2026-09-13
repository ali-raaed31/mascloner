"""Seed sync paths and rclone performance settings in SQLite.

Revision ID: 20250101_000001
Revises: 20241226_000001
Create Date: 2025-01-01 00:00:01
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250101_000001"
down_revision: Union[str, None] = "20241226_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add provenance column using batch mode for SQLite support
    insp = sa.inspect(conn)
    columns = [c["name"] for c in insp.get_columns("config")]
    if "provenance" not in columns:
        with op.batch_alter_table("config") as batch_op:
            batch_op.add_column(
                sa.Column("provenance", sa.String(50), nullable=True)
            )

    # 2. Mark any pre-existing rows as imported_legacy
    conn.execute(
        sa.text("UPDATE config SET provenance = 'imported_legacy'")
    )

    # 3. Inspect existing keys
    existing_keys = set()
    result = conn.execute(sa.text("SELECT key FROM config"))
    for row in result:
        existing_keys.add(row[0])

    # 4. Read environment fallback values (including from .env if base dir or env file is set)
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
                    # File-based environment values take precedence for that installation
                    env_vars[k] = v
        except Exception:
            pass

    # Map of (setting_key, env_var_name, default_value)
    settings_to_seed = [
        ("gdrive_src", "GDRIVE_SRC", ""),
        ("nc_dest_path", "NC_DEST_PATH", ""),
        ("transfers", "RCLONE_TRANSFERS", "4"),
        ("checkers", "RCLONE_CHECKERS", "8"),
        ("tpslimit", "RCLONE_TPSLIMIT", "10"),
        ("tpslimit_burst", "RCLONE_TPSLIMIT_BURST", "1"),
        ("buffer_size", "RCLONE_BUFFER_SIZE", "32Mi"),
        ("drive_chunk_size", "RCLONE_DRIVE_CHUNK_SIZE", "64M"),
        ("drive_upload_cutoff", "RCLONE_DRIVE_UPLOAD_CUTOFF", "128M"),
        ("fast_list", "RCLONE_FAST_LIST", "false"),
    ]

    inserts = []
    for key, env_key, default_val in settings_to_seed:
        if key not in existing_keys:
            if env_key in env_vars and env_vars[env_key] != "":
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

    if inserts:
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
    # Remove newly introduced performance keys that didn't exist in 20241226_000001
    perf_keys = [
        "transfers",
        "checkers",
        "tpslimit",
        "tpslimit_burst",
        "buffer_size",
        "drive_chunk_size",
        "drive_upload_cutoff",
        "fast_list",
    ]
    for key in perf_keys:
        conn.execute(sa.text("DELETE FROM config WHERE key = :key"), {"key": key})

    with op.batch_alter_table("config") as batch_op:
        batch_op.drop_column("provenance")
