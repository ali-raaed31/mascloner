"""SyncExecutor module (ADR 0005, ADR 0007)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..api.models import FileEvent, Run, SyncStatus
from ..configuration import Configuration
from ..configuration.lease import get_process_lease
from ..configuration.models import RclonePerformanceSettings, SyncPathsSettings
from .command_builder import RcloneCommandBuilder
from .exceptions import (
    ActiveRunConflictError,
    ExecutionError,
    ExecutionTimeoutError,
    InvalidRunStateError,
    SubprocessLaunchError,
)
from .models import AbortResult, ActiveRunSnapshot, FileEventEntry, TriggerResult
from .output_parser import RcloneOutputParser

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _redact_secrets(text: str) -> str:
    """Redact passwords and tokens from string output."""
    redacted = re.sub(r'(access_token["\s:=]+)[^\s",}]+', r'\1***REDACTED***', text)
    redacted = re.sub(r'(--pass(?:word)?["\s:=]+)[^\s",}]+', r'\1***REDACTED***', redacted)
    redacted = re.sub(r'(pass["\s:=]+)[^\s",}]+', r'\1***REDACTED***', redacted)
    return redacted


class SyncExecutor:
    """Narrow execution engine for Google Drive -> Nextcloud SyncRuns."""

    _instance: Optional["SyncExecutor"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        session_factory: Optional[Callable[[], Session]] = None,
        rclone_conf_path: Optional[Path] = None,
        rclone_bin: Optional[Path | str] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        if session_factory:
            self._session_factory = session_factory
        else:
            from ..api.db import get_db_session
            self._session_factory = get_db_session

        self._rclone_conf = rclone_conf_path
        self._rclone_bin = str(rclone_bin or os.environ.get("RCLONE_BIN") or "rclone")
        self._log_dir = log_dir

        self._run_lock = threading.Lock()
        self._active_run_id: Optional[int] = None
        self._active_log_path: Optional[Path] = None
        self._active_process: Optional[subprocess.Popen] = None
        self._abort_requested = False
        self._snapshot_lock = threading.Lock()
        self._current_snapshot: Optional[ActiveRunSnapshot] = None
        self._execution_thread: Optional[threading.Thread] = None
        self._is_shutting_down = False

    @classmethod
    def get_instance(
        cls,
        session_factory: Optional[Callable[[], Session]] = None,
        rclone_conf_path: Optional[Path] = None,
        rclone_bin: Optional[Path | str] = None,
        log_dir: Optional[Path] = None,
    ) -> "SyncExecutor":
        """Get or create singleton SyncExecutor."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(
                    session_factory=session_factory,
                    rclone_conf_path=rclone_conf_path,
                    rclone_bin=rclone_bin,
                    log_dir=log_dir,
                )
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for tests."""
        with cls._instance_lock:
            if cls._instance is not None:
                try:
                    cls._instance.shutdown(timeout=2.0)
                except Exception:
                    pass
            cls._instance = None

    def _resolve_rclone_conf(self) -> Path:
        if self._rclone_conf:
            return Path(self._rclone_conf)
        from ..api.config import get_rclone_conf_path
        return Path(get_rclone_conf_path())

    def _resolve_log_dir(self) -> Path:
        if self._log_dir:
            return Path(self._log_dir)
        from ..api.config import get_log_dir
        return Path(get_log_dir())

    def is_running(self) -> bool:
        """Return True if an execution is currently in progress."""
        with self._run_lock:
            return self._active_run_id is not None

    def is_shutting_down(self) -> bool:
        """Return True if executor has started shutting down."""
        with self._run_lock:
            return self._is_shutting_down

    def get_active_run_id(self) -> Optional[int]:
        """Return active run ID if one is executing."""
        with self._run_lock:
            return self._active_run_id

    # --- Triggering execution ---

    def trigger_run(
        self,
        trigger_type: str = "manual",
        dry_run: bool = False,
        wait: bool = False,
    ) -> TriggerResult:
        """Trigger a SyncRun enforcing canonical single-active-run lifecycle."""
        with self._run_lock:
            if self._is_shutting_down:
                logger.warning("Sync request rejected: SyncExecutor is shutting down")
                return TriggerResult(
                    accepted=False,
                    run_id=None,
                    status=SyncStatus.SKIPPED,
                    message="SyncExecutor is shutting down",
                )

            # 1. Deterministic overlap policy: check if already active
            if self._active_run_id is not None:
                with self._session_factory() as db:
                    now = _utc_now()
                    skipped_run = Run(
                        status=SyncStatus.SKIPPED,
                        started_at=now,
                        finished_at=now,
                        message=f"Sync run skipped: another synchronization run is currently active ({trigger_type} trigger)",
                    )
                    db.add(skipped_run)
                    db.commit()
                    db.refresh(skipped_run)
                    skipped_id = skipped_run.id

                logger.warning(
                    "Sync request rejected: run %d already active; recorded skipped run %d (%s trigger)",
                    self._active_run_id,
                    skipped_id,
                    trigger_type,
                )
                return TriggerResult(
                    accepted=False,
                    run_id=skipped_id,
                    status=SyncStatus.SKIPPED,
                    message="Sync already in progress",
                )

            # Check if database has any stranded RUNNING runs
            with self._session_factory() as db:
                stranded = db.execute(
                    select(Run).where(Run.status == SyncStatus.RUNNING).order_by(desc(Run.started_at))
                ).scalars().first()
                if stranded:
                    now = _utc_now()
                    skipped_run = Run(
                        status=SyncStatus.SKIPPED,
                        started_at=now,
                        finished_at=now,
                        message=f"Sync run skipped: another synchronization run is marked active in database ({trigger_type} trigger)",
                    )
                    db.add(skipped_run)
                    db.commit()
                    db.refresh(skipped_run)
                    return TriggerResult(
                        accepted=False,
                        run_id=skipped_run.id,
                        status=SyncStatus.SKIPPED,
                        message="Sync already in progress",
                    )

                # 2. Prepare durable PENDING run
                log_dir = self._resolve_log_dir()
                log_dir.mkdir(parents=True, exist_ok=True)
                timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
                log_file = log_dir / f"sync-{timestamp}.log"

                run = Run(
                    status=SyncStatus.PENDING,
                    started_at=_utc_now(),
                    log_path=str(log_file),
                    message=f"{trigger_type.capitalize()} sync queued for execution",
                )
                db.add(run)
                db.commit()
                db.refresh(run)
                run_id = run.id

            # 3. Capture immutable snapshot before background dispatch
            rclone_conf = self._resolve_rclone_conf()
            cfg_module = Configuration(
                session_factory=self._session_factory,
                rclone_conf_path=rclone_conf,
            )
            paths_snapshot, perf_snapshot = cfg_module.create_run_snapshot()

            # 4. Set state and spawn background thread
            self._active_run_id = run_id
            self._active_log_path = log_file
            self._abort_requested = False

            with self._snapshot_lock:
                self._current_snapshot = ActiveRunSnapshot(
                    run_id=run_id,
                    status=SyncStatus.PENDING,
                    started_at=_utc_now(),
                    is_active=True,
                    message=f"{trigger_type.capitalize()} sync queued for execution",
                )

            worker_thread = threading.Thread(
                target=self._run_worker,
                args=(run_id, log_file, paths_snapshot, perf_snapshot, dry_run),
                daemon=True,
                name=f"SyncExecutor-{run_id}",
            )
            self._execution_thread = worker_thread
            worker_thread.start()

            logger.info("SyncExecutor: started %s run %d", trigger_type, run_id)

        if wait:
            worker_thread.join()
            with self._session_factory() as db:
                fin_run = db.get(Run, run_id)
                status_res = fin_run.status if fin_run else SyncStatus.COMPLETED
                msg_res = fin_run.message if fin_run else "Sync execution finished"
            return TriggerResult(
                accepted=True,
                run_id=run_id,
                status=status_res,
                message=msg_res,
            )

        return TriggerResult(
            accepted=True,
            run_id=run_id,
            status=SyncStatus.PENDING,
            message="Sync triggered successfully",
        )

    def trigger_manual_run(self, dry_run: bool = False, wait: bool = False) -> TriggerResult:
        """Trigger a manual SyncRun."""
        return self.trigger_run(trigger_type="manual", dry_run=dry_run, wait=wait)

    def trigger_scheduled_run(self, dry_run: bool = False, wait: bool = False) -> TriggerResult:
        """Trigger a scheduled SyncRun."""
        return self.trigger_run(trigger_type="schedule", dry_run=dry_run, wait=wait)

    # --- Background worker ---

    def _run_worker(
        self,
        run_id: int,
        log_file_path: Path,
        paths: SyncPathsSettings,
        perf: RclonePerformanceSettings,
        dry_run: bool,
    ) -> None:
        """Background execution worker holding lease and updating run state."""
        rclone_conf = self._resolve_rclone_conf()
        lease = get_process_lease()

        terminal_status = SyncStatus.FAILED
        terminal_message = "Unexpected execution termination"
        num_added = 0
        num_updated = 0
        bytes_transferred = 0
        errors = 0
        file_events: List[FileEventEntry] = []

        try:
            # 1. Short DB transaction: transition to RUNNING
            with self._session_factory() as db:
                active_run = db.get(Run, run_id)
                if active_run:
                    active_run.transition_to(SyncStatus.RUNNING)
                    active_run.message = "Sync in progress"
                    db.commit()

            with self._snapshot_lock:
                if self._current_snapshot and self._current_snapshot.run_id == run_id:
                    self._current_snapshot = ActiveRunSnapshot(
                        run_id=run_id,
                        status=SyncStatus.RUNNING,
                        started_at=self._current_snapshot.started_at,
                        is_active=True,
                        message="Sync in progress",
                    )

            # 2. Build command strictly from snapshot and fixed endpoints
            cmd = RcloneCommandBuilder.build_sync_command(
                paths=paths,
                perf=perf,
                rclone_conf_path=rclone_conf,
                log_file_path=log_file_path,
                rclone_bin=self._rclone_bin,
                dry_run=dry_run,
            )

            # Check if abort or shutdown happened before lease/launch
            if self._abort_requested or self._is_shutting_down:
                terminal_status = SyncStatus.ABORTED
                terminal_message = "Sync aborted prior to launch"
                return

            # 3. Hold ConfigurationLease for the subprocess lifetime
            with lease.acquire(holder=f"SyncRun-{run_id}", timeout=5.0):
                if self._abort_requested or self._is_shutting_down:
                    terminal_status = SyncStatus.ABORTED
                    terminal_message = "Sync aborted prior to launch"
                    return
                logger.info("SyncExecutor: acquired lease for run %d, launching rclone", run_id)

                try:
                    self._active_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                except Exception as exc:
                    terminal_status = SyncStatus.FAILED
                    terminal_message = _redact_secrets(f"Failed to launch rclone: {exc}")
                    logger.error("SyncExecutor: launch failed for run %d: %s", run_id, exc)
                    return

                # 4. Stream subprocess output line-by-line without holding any DB transaction
                recent_events_buf: List[Dict[str, Any]] = []

                if self._active_process.stdout:
                    for line in iter(self._active_process.stdout.readline, ""):
                        if not line:
                            break

                        event, stats = RcloneOutputParser.parse_line(line)

                        if event:
                            file_events.append(event)
                            if event.action == "copy":
                                num_added += 1
                            elif event.action in ("replace", "update"):
                                num_updated += 1
                            elif event.action == "error":
                                errors += 1

                            recent_events_buf.append({
                                "action": event.action,
                                "path": event.file_path,
                                "size": event.file_size,
                                "timestamp": event.timestamp.isoformat(),
                            })
                            if len(recent_events_buf) > 50:
                                recent_events_buf.pop(0)

                        if stats:
                            bytes_transferred = int(stats.get("bytes", bytes_transferred) or 0)
                            errors = int(stats.get("errors", errors) or errors)
                            transfers = int(stats.get("transfers", num_added + num_updated) or 0)
                            total_bytes = stats.get("totalBytes")
                            speed = stats.get("speed")
                            eta = stats.get("eta")
                            pct = None
                            if total_bytes and total_bytes > 0:
                                pct = round((bytes_transferred / total_bytes) * 100, 1)

                            with self._snapshot_lock:
                                self._current_snapshot = ActiveRunSnapshot(
                                    run_id=run_id,
                                    status=SyncStatus.RUNNING,
                                    started_at=self._current_snapshot.started_at if self._current_snapshot else _utc_now(),
                                    is_active=True,
                                    bytes_transferred=bytes_transferred,
                                    total_bytes=total_bytes,
                                    percentage=pct,
                                    speed_bps=speed,
                                    files_transferred=transfers,
                                    eta_seconds=eta,
                                    errors=errors,
                                    recent_events=list(recent_events_buf),
                                    message="Sync in progress",
                                )

                    self._active_process.stdout.close()

                retcode = self._active_process.wait()
                logger.info("SyncExecutor: rclone exited with code %d for run %d", retcode, run_id)

                # Also inspect log file in case rclone wrote exclusively to --log-file
                if log_file_path.exists():
                    try:
                        with open(log_file_path, "r", encoding="utf-8") as lf:
                            for lf_line in lf:
                                f_evt, f_stats = RcloneOutputParser.parse_line(lf_line)
                                if f_evt and not any(e.file_path == f_evt.file_path and e.action == f_evt.action for e in file_events):
                                    file_events.append(f_evt)
                                    if f_evt.action == "copy":
                                        num_added += 1
                                    elif f_evt.action in ("replace", "update"):
                                        num_updated += 1
                                    elif f_evt.action == "error":
                                        errors += 1
                    except Exception as err:
                        logger.warning("SyncExecutor: failed reading log file %s: %s", log_file_path, err)

                # 5. Determine terminal status
                if self._abort_requested or self._is_shutting_down or retcode in (-signal.SIGTERM, -signal.SIGKILL, 143, 137):
                    terminal_status = SyncStatus.ABORTED
                    terminal_message = "Sync aborted: user stop requested or service shutdown"
                elif retcode == 0:
                    terminal_status = SyncStatus.COMPLETED
                    terminal_message = "Sync completed successfully"
                else:
                    terminal_status = SyncStatus.FAILED
                    terminal_message = f"rclone exited with code {retcode}"

        except Exception as exc:
            terminal_status = SyncStatus.FAILED
            terminal_message = _redact_secrets(f"Execution error: {exc}")
            logger.error("SyncExecutor: unexpected exception during run %d: %s", run_id, exc)

        finally:
            # 6. Record terminal state in short DB transaction
            try:
                with self._session_factory() as db:
                    active_run = db.get(Run, run_id)
                    if active_run:
                        active_run.transition_to(terminal_status, message=terminal_message)
                        active_run.finished_at = _utc_now()
                        active_run.num_added = num_added
                        active_run.num_updated = num_updated
                        active_run.bytes_transferred = bytes_transferred
                        active_run.errors = errors

                        # Persist file events
                        for ev in file_events:
                            db.add(
                                FileEvent(
                                    run_id=run_id,
                                    timestamp=ev.timestamp,
                                    action=ev.action,
                                    file_path=ev.file_path,
                                    file_size=ev.file_size,
                                    file_hash=ev.file_hash,
                                    message=ev.message,
                                )
                            )
                        db.commit()
            except Exception as exc:
                logger.error("SyncExecutor: failed to save terminal state for run %d: %s", run_id, exc)

            # 7. Update final snapshot and clean up handles
            with self._snapshot_lock:
                self._current_snapshot = ActiveRunSnapshot(
                    run_id=run_id,
                    status=terminal_status,
                    started_at=self._current_snapshot.started_at if self._current_snapshot else _utc_now(),
                    is_active=False,
                    bytes_transferred=bytes_transferred,
                    files_transferred=num_added + num_updated,
                    errors=errors,
                    message=terminal_message,
                )

            with self._run_lock:
                self._active_process = None
                self._active_run_id = None
                self._active_log_path = None
                self._abort_requested = False

    # --- Live monitoring & logs ---

    def get_active_snapshot(self) -> Optional[ActiveRunSnapshot]:
        """Return real-time snapshot of active run, or None if inactive."""
        with self._snapshot_lock:
            if self._current_snapshot and self._current_snapshot.is_active:
                return self._current_snapshot

        # Fallback to database check
        with self._session_factory() as db:
            active_run = db.execute(
                select(Run).where(Run.status == SyncStatus.RUNNING).order_by(desc(Run.started_at))
            ).scalars().first()

            if active_run:
                return ActiveRunSnapshot(
                    run_id=active_run.id,
                    status=active_run.status,
                    started_at=active_run.started_at,
                    is_active=True,
                    bytes_transferred=active_run.bytes_transferred or 0,
                    files_transferred=(active_run.num_added or 0) + (active_run.num_updated or 0),
                    errors=active_run.errors or 0,
                    message=active_run.message,
                )

        return None

    def request_abort(self, run_id: Optional[int] = None) -> AbortResult:
        """Request graceful abort of the currently executing run."""
        with self._run_lock:
            if self._active_run_id is None:
                return AbortResult(
                    requested=False,
                    run_id=run_id,
                    message="No active sync run to abort",
                )

            if run_id is not None and self._active_run_id != run_id:
                return AbortResult(
                    requested=False,
                    run_id=run_id,
                    message=f"Run {run_id} is not the active sync process (active run: {self._active_run_id})",
                )

            target_id = self._active_run_id
            self._abort_requested = True

            if self._active_process is not None:
                try:
                    self._active_process.send_signal(signal.SIGTERM)
                    logger.info("SyncExecutor: sent SIGTERM to process for run %d", target_id)
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    logger.error("SyncExecutor: failed to send SIGTERM to run %d: %s", target_id, exc)

            return AbortResult(
                requested=True,
                run_id=target_id,
                message="Stop requested - rclone will finish current file and exit",
            )

    def tail_log_file(
        self,
        run_id: int,
        since_line: int = 0,
        limit: int = 100,
    ) -> Tuple[List[Dict[str, Any]], int, bool]:
        """Tail log lines for a running or completed sync."""
        with self._run_lock:
            is_live = (self._active_run_id == run_id)
            log_path = self._active_log_path if is_live else None

        if not log_path:
            with self._session_factory() as db:
                run = db.get(Run, run_id)
                if run and run.log_path:
                    log_path = Path(run.log_path)

        if not log_path or not log_path.exists():
            return [], since_line, is_live

        logs: List[Dict[str, Any]] = []
        next_line = since_line

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f):
                    next_line = line_num + 1
                    if line_num < since_line:
                        continue
                    if len(logs) >= limit:
                        break
                    clean = line.strip()
                    if not clean:
                        continue
                    try:
                        obj = json.loads(clean)
                        logs.append({
                            "line": line_num,
                            "timestamp": obj.get("time", ""),
                            "level": obj.get("level", "info"),
                            "message": _redact_secrets(obj.get("msg", "")),
                            "object": obj.get("object", ""),
                            "size": obj.get("size", 0),
                        })
                    except json.JSONDecodeError:
                        logs.append({
                            "line": line_num,
                            "timestamp": "",
                            "level": "info",
                            "message": _redact_secrets(clean),
                            "object": "",
                            "size": 0,
                        })
        except Exception as exc:
            logger.error("SyncExecutor: failed to read log file %s: %s", log_path, exc)

        return logs, next_line, is_live


    def shutdown(self, timeout: float = 10.0) -> None:
        """Gracefully shut down executor, terminating active run within timeout."""
        with self._run_lock:
            self._is_shutting_down = True
            active_id = self._active_run_id
            thread = self._execution_thread
            proc = self._active_process

        if active_id is not None:
            logger.info("SyncExecutor shutdown: terminating active run %d within %.1fs", active_id, timeout)
            self.request_abort(active_id)

            if thread and thread.is_alive():
                thread.join(timeout=timeout)

            with self._run_lock:
                proc = self._active_process
            if proc and proc.poll() is None:
                logger.warning("SyncExecutor shutdown: process did not exit within timeout; killing with SIGKILL")
                try:
                    proc.kill()
                except Exception as exc:
                    logger.error("SyncExecutor shutdown: error killing process: %s", exc)

            if thread and thread.is_alive():
                thread.join(timeout=2.0)

            try:
                with self._session_factory() as db:
                    run = db.get(Run, active_id)
                    if run and run.status in (SyncStatus.PENDING, SyncStatus.RUNNING):
                        now = _utc_now()
                        run.transition_to(
                            SyncStatus.ABORTED,
                            message="Sync aborted: service shutdown",
                        )
                        run.finished_at = now
                        db.commit()
                        logger.info("SyncExecutor shutdown: marked run %d as aborted", active_id)
            except Exception as exc:
                logger.error("SyncExecutor shutdown: error updating database for run %d: %s", active_id, exc)

        with self._snapshot_lock:
            if self._current_snapshot and self._current_snapshot.is_active:
                self._current_snapshot = ActiveRunSnapshot(
                    run_id=self._current_snapshot.run_id,
                    status=SyncStatus.ABORTED,
                    started_at=self._current_snapshot.started_at,
                    is_active=False,
                    message="Sync aborted: service shutdown",
                )

        logger.info("SyncExecutor shutdown complete")
