#!/usr/bin/env python3
"""Operational script to execute online consistency-checked SQLite backup for MasCloner."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).parent.parent.parent.resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.maintenance.backup import OnlineBackupError, perform_online_backup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mascloner-backup")


def main() -> int:
    parser = argparse.ArgumentParser(description="MasCloner Online Database Backup Tool")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to live SQLite database (defaults to MASCLONER_DB_PATH or /srv/mascloner/data/mascloner.db)",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("/var/backups/mascloner"),
        help="Directory to store backup file",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help="Explicit target file path for backup (overrides --target-dir)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    args = parser.parse_args()

    # Determine source path
    if args.source:
        source_db = args.source
    elif "MASCLONER_DB_PATH" in os.environ:
        source_db = Path(os.environ["MASCLONER_DB_PATH"])
    else:
        base_dir = Path(os.environ.get("MASCLONER_BASE_DIR", "/srv/mascloner"))
        source_db = base_dir / "data" / "mascloner.db"

    # Determine target path
    if args.target:
        target_path = args.target
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target_path = args.target_dir / f"mascloner_backup_{timestamp}_database.db"

    try:
        logger.info("Initiating online backup: %s -> %s", source_db, target_path)
        info = perform_online_backup(source_db_path=source_db, target_path=target_path)
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            logger.info("Backup succeeded: %s (%d bytes)", info["target"], info["size_bytes"])
        return 0
    except OnlineBackupError as err:
        logger.error("Backup failed: %s", err)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error during backup: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
