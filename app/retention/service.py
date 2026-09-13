"""RetentionService implementing 60-day history retention (ADR 0008, Issue #13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Callable, List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..api.db import get_db_session
from ..api.models import ConfigKV, FileEvent, Run, SyncStatus
from ..configuration import Configuration, RetentionPolicySettings
from .models import RetentionReport

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = (
    SyncStatus.COMPLETED,
    SyncStatus.FAILED,
    SyncStatus.ABORTED,
    SyncStatus.SKIPPED,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RetentionService:
    """Service that executes bounded, idempotent history retention passes."""

    _instance: Optional[RetentionService] = None
    _instance_lock = threading.Lock()

    def __init__(self, session_factory: Optional[Callable[[], Session]] = None) -> None:
        self._session_factory = session_factory or get_db_session
        self._lock = threading.Lock()
        self._last_report: Optional[RetentionReport] = None

    @classmethod
    def get_instance(
        cls, session_factory: Optional[Callable[[], Session]] = None
    ) -> RetentionService:
        """Get or create singleton RetentionService."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(session_factory=session_factory)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (used in tests)."""
        with cls._instance_lock:
            cls._instance = None

    def get_last_report(self) -> Optional[RetentionReport]:
        """Return the most recent retention report (in-memory or from database)."""
        if self._last_report is not None:
            return self._last_report

        try:
            with self._session_factory() as db:
                item = db.execute(
                    select(ConfigKV).where(ConfigKV.key == "retention_last_report")
                ).scalars().first()
                if item and item.value:
                    data = json.loads(item.value)
                    self._last_report = RetentionReport.model_validate(data)
                    return self._last_report
        except Exception as exc:
            logger.debug("Could not load last retention report from DB: %s", exc)

        return None

    def _persist_last_report(self, report: RetentionReport) -> None:
        """Persist report to database so it survives process restarts."""
        self._last_report = report
        try:
            with self._session_factory() as db:
                raw_json = report.model_dump_json()
                item = db.execute(
                    select(ConfigKV).where(ConfigKV.key == "retention_last_report")
                ).scalars().first()
                if item:
                    item.value = raw_json
                    item.updated_at = _utc_now()
                else:
                    db.add(
                        ConfigKV(
                            key="retention_last_report",
                            value=raw_json,
                            updated_at=_utc_now(),
                            provenance="system",
                        )
                    )
                db.commit()
        except Exception as exc:
            logger.warning("Failed to persist retention report to DB: %s", exc)

    def apply_retention(
        self,
        retention_days: Optional[int] = None,
        dry_run: bool = False,
        batch_size: int = 100,
        now: Optional[datetime] = None,
    ) -> RetentionReport:
        """Execute a retention pass against terminal SyncRuns older than retention_days.

        Never removes active runs ('pending' or 'running').
        Operates in short bounded transactions per batch.
        """
        # Ensure only one retention pass runs concurrently
        if not self._lock.acquire(blocking=False):
            logger.warning("Retention pass already running, skipping overlapping execution")
            now_t = now or _utc_now()
            return RetentionReport(
                started_at=now_t,
                finished_at=now_t,
                cutoff_utc=now_t,
                retention_days=retention_days or 60,
                is_dry_run=dry_run,
                success=False,
                error="Retention pass already in progress",
            )

        start_time = now or _utc_now()

        try:
            # 1. Resolve retention days
            eff_days = retention_days
            if eff_days is None:
                try:
                    cfg = Configuration(session_factory=self._session_factory)
                    eff_days = cfg.get_retention_policy().retention_days
                except Exception as exc:
                    logger.warning("Could not read RetentionPolicy from Configuration: %s", exc)
                    eff_days = 60

            cutoff = start_time - timedelta(days=eff_days)

            runs_evaluated = 0
            runs_deleted = 0
            events_deleted = 0
            logs_deleted = 0
            log_deletion_failures: List[str] = []

            # 2. Dry run evaluation
            if dry_run:
                with self._session_factory() as db:
                    # Query eligible runs: terminal status and completion timestamp < cutoff
                    # In SQLite, coalesce(finished_at, started_at) handles runs where finished_at was not recorded
                    stmt = (
                        select(Run)
                        .where(Run.status.in_(_TERMINAL_STATUSES))
                        .where(func.coalesce(Run.finished_at, Run.started_at) < cutoff)
                        .order_by(Run.id.asc())
                    )
                    eligible_runs = db.execute(stmt).scalars().all()
                    runs_evaluated = len(eligible_runs)
                    runs_deleted = len(eligible_runs)

                    if eligible_runs:
                        eligible_ids = [r.id for r in eligible_runs]
                        evt_count = db.execute(
                            select(func.count(FileEvent.id)).where(FileEvent.run_id.in_(eligible_ids))
                        ).scalar() or 0
                        events_deleted = evt_count

                        for r in eligible_runs:
                            if r.log_path and Path(r.log_path).exists():
                                logs_deleted += 1

                fin_time = now or _utc_now()
                report = RetentionReport(
                    started_at=start_time,
                    finished_at=fin_time,
                    cutoff_utc=cutoff,
                    retention_days=eff_days,
                    runs_evaluated=runs_evaluated,
                    runs_deleted=runs_deleted,
                    events_deleted=events_deleted,
                    logs_deleted=logs_deleted,
                    log_deletion_failures=[],
                    is_dry_run=True,
                    success=True,
                )
                logger.info(
                    "Retention dry-run complete: would prune %d runs, %d events, %d logs older than %s",
                    runs_deleted,
                    events_deleted,
                    logs_deleted,
                    cutoff.isoformat(),
                )
                return report

            # 3. Apply mode: process in bounded batches
            while True:
                with self._session_factory() as db:
                    stmt = (
                        select(Run)
                        .where(Run.status.in_(_TERMINAL_STATUSES))
                        .where(func.coalesce(Run.finished_at, Run.started_at) < cutoff)
                        .order_by(Run.id.asc())
                        .limit(batch_size)
                    )
                    batch_runs = db.execute(stmt).scalars().all()
                    if not batch_runs:
                        break

                    batch_ids = [r.id for r in batch_runs]
                    runs_evaluated += len(batch_runs)

                    # A. Log files cleanup
                    for r in batch_runs:
                        if r.log_path:
                            lp = Path(r.log_path)
                            if lp.is_file():
                                try:
                                    lp.unlink(missing_ok=True)
                                    logs_deleted += 1
                                except Exception as exc:
                                    fail_msg = f"Failed to delete log file for run {r.id}: {exc}"
                                    logger.warning("Retention: %s", fail_msg)
                                    log_deletion_failures.append(fail_msg)

                    # B. Delete FileEvents in short transaction
                    evt_del = db.execute(
                        delete(FileEvent).where(FileEvent.run_id.in_(batch_ids))
                    )
                    events_deleted += evt_del.rowcount if evt_del.rowcount >= 0 else 0

                    # C. Delete Runs in same transaction
                    run_del = db.execute(
                        delete(Run).where(Run.id.in_(batch_ids))
                    )
                    runs_deleted += run_del.rowcount if run_del.rowcount >= 0 else len(batch_ids)

                    db.commit()

            fin_time = now or _utc_now()
            report = RetentionReport(
                started_at=start_time,
                finished_at=fin_time,
                cutoff_utc=cutoff,
                retention_days=eff_days,
                runs_evaluated=runs_evaluated,
                runs_deleted=runs_deleted,
                events_deleted=events_deleted,
                logs_deleted=logs_deleted,
                log_deletion_failures=log_deletion_failures,
                is_dry_run=False,
                success=True,
            )

            self._persist_last_report(report)
            logger.info(
                "Retention pass completed: deleted %d runs, %d events, %d logs (duration: %.2fs)",
                runs_deleted,
                events_deleted,
                logs_deleted,
                report.duration_seconds,
            )
            return report

        except Exception as exc:
            fin_time = now or _utc_now()
            logger.error("Retention pass failed: %s", exc)
            report = RetentionReport(
                started_at=start_time,
                finished_at=fin_time,
                cutoff_utc=cutoff if "cutoff" in locals() else start_time,
                retention_days=eff_days if "eff_days" in locals() else 60,
                runs_evaluated=runs_evaluated if "runs_evaluated" in locals() else 0,
                runs_deleted=runs_deleted if "runs_deleted" in locals() else 0,
                events_deleted=events_deleted if "events_deleted" in locals() else 0,
                logs_deleted=logs_deleted if "logs_deleted" in locals() else 0,
                log_deletion_failures=log_deletion_failures if "log_deletion_failures" in locals() else [],
                is_dry_run=dry_run,
                success=False,
                error=str(exc),
            )
            self._persist_last_report(report)
            return report

        finally:
            self._lock.release()
