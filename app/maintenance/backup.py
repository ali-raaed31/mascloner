"""Online SQLite backup with integrity and restore verification.

Uses SQLite's online backup API (sqlite3.Connection.backup) to safely copy
a running database (even under concurrent WAL writes) without table locks,
runs PRAGMA integrity_check, and verifies application readability against a
disposable connection before declaring success.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict

logger = logging.getLogger(__name__)


class OnlineBackupError(RuntimeError):
    """Raised when an online backup or verification fails."""


def verify_database_integrity(db_path: Path | str) -> bool:
    """Run SQLite integrity and foreign key checks on a database file."""
    path_obj = Path(db_path)
    if not path_obj.exists():
        return False
    db_path = path_obj
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("PRAGMA integrity_check")
        rows = cursor.fetchall()
        if not rows or rows[0][0] != "ok":
            logger.error("PRAGMA integrity_check failed on %s: %s", db_path, rows)
            conn.close()
            return False

        cursor.execute("PRAGMA foreign_key_check")
        fk_errors = cursor.fetchall()
        conn.close()

        if fk_errors:
            logger.error("PRAGMA foreign_key_check failed on %s: %s", db_path, fk_errors)
            return False

        return True
    except Exception as exc:
        logger.error("Failed to verify integrity for %s: %s", db_path, exc)
        return False


def perform_online_backup(
    source_db_path: Path,
    target_path: Path,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Perform a consistent online SQLite backup using sqlite3.Connection.backup().

    Ensures:
    1. Online copy without blocking concurrent reads or writes in WAL mode.
    2. Atomic file write with restrictive 0600 permissions.
    3. PRAGMA integrity_check and PRAGMA foreign_key_check.
    4. Disposable application-level read test on key tables.
    5. Cleanup of target file and zero mutation to live database on failure.
    """
    source_path = Path(source_db_path).resolve()
    dest_path = Path(target_path).resolve()

    if not source_path.exists():
        raise OnlineBackupError(f"Source database file does not exist: {source_path}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Temporary file for atomic write
    temp_target = dest_path.with_name(f"{dest_path.name}.tmp.{os.getpid()}")

    src_conn = None
    dest_conn = None

    try:
        src_conn = sqlite3.connect(str(source_path), timeout=timeout)
        dest_conn = sqlite3.connect(str(temp_target))

        # Perform online backup
        src_conn.backup(dest_conn, pages=100)

        dest_conn.commit()
        dest_conn.close()
        dest_conn = None
        src_conn.close()
        src_conn = None

        # Restrict permissions to owner read/write (0600)
        os.chmod(temp_target, 0o600)

        # 1. Check integrity of the backup file
        if not verify_database_integrity(temp_target):
            raise OnlineBackupError(f"Integrity check failed for backup artifact at {temp_target}")

        # 2. Disposable application-level verification
        test_conn = sqlite3.connect(str(temp_target))
        cursor = test_conn.cursor()
        cursor.execute("SELECT count(*) FROM config")
        cursor.fetchone()
        test_conn.close()

        # Atomic rename to final target destination
        temp_target.replace(dest_path)
        os.chmod(dest_path, 0o600)

        size_bytes = dest_path.stat().st_size
        logger.info("Online backup completed successfully: %s (%d bytes)", dest_path, size_bytes)

        return {
            "source": str(source_path),
            "target": str(dest_path),
            "size_bytes": size_bytes,
            "verified": True,
            "integrity_check": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        logger.error("Online backup failed: %s", exc)
        if temp_target.exists():
            try:
                temp_target.unlink()
            except OSError:
                pass
        if dest_path.exists() and dest_path != source_path:
            try:
                dest_path.unlink()
            except OSError:
                pass
        raise OnlineBackupError(f"Online backup failed: {exc}") from exc

    finally:
        if dest_conn:
            try:
                dest_conn.close()
            except Exception:
                pass
        if src_conn:
            try:
                src_conn.close()
            except Exception:
                pass
