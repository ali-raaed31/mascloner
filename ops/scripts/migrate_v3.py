#!/usr/bin/env python3
"""Operational script to execute v3 architecture migration and rollback for MasCloner (Issue #14)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to sys.path
repo_root = Path(__file__).parent.parent.parent.resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.migration import MigrationMode, MigrationService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mascloner-migration")


def main() -> int:
    parser = argparse.ArgumentParser(description="MasCloner v3 Migration and Rollback Tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Run preflight checks only")
    group.add_argument("--dry-run", action="store_true", help="Perform non-mutating dry-run calculation")
    group.add_argument("--apply", action="store_true", help="Apply migration and cutover")
    group.add_argument("--rollback", type=Path, help="Rollback using specified recovery bundle directory")

    parser.add_argument("--base-dir", type=Path, default=None, help="Base installation directory")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Backup root directory")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")

    args = parser.parse_args()

    service = MigrationService(
        base_dir=args.base_dir,
        backup_root=args.backup_dir,
    )

    if args.rollback or args.apply:
        logger.error(
            "Use 'mascloner migrate --apply' or '--rollback' for mutable cutover operations; "
            "the CLI stops and confirms services before changing SQLite or configuration files."
        )
        return 1

    if args.check:
        logger.info("Executing migration preflight checks")
        report = service.run_migration(mode=MigrationMode.CHECK)
    elif args.dry_run:
        logger.info("Simulating migration in dry-run mode (0 mutations)")
        report = service.run_migration(mode=MigrationMode.DRY_RUN)
    else:
        logger.error("No valid mode selected")
        return 1

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        if report.success:
            logger.info("Operation succeeded: mode=%s, step=%s", report.mode.value, report.current_step.value)
            if report.recovery_bundle:
                logger.info("Recovery bundle: %s", report.recovery_bundle.bundle_dir)
        else:
            logger.error("Operation failed: %s", report.error)

    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
