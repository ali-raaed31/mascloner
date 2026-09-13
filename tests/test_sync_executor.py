"""Hermetic tests for SyncExecutor module (ADR 0005, ADR 0007)."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Generator
import pytest
from sqlalchemy import desc, select

from app.api.db import get_db_session
from app.api.models import FileEvent, Run, SyncStatus
from app.configuration import Configuration
from app.configuration.lease import ConfigurationLeaseError, get_process_lease
from app.execution import (
    ActiveRunConflictError,
    ActiveRunSnapshot,
    RcloneCommandBuilder,
    SyncExecutor,
)
from tests.harness.installation import InstallationRoot
from tests.harness.fake_rclone import FakeRcloneScenario


@pytest.fixture
def isolated_install() -> Generator[InstallationRoot, None, None]:
    """Create isolated test environment."""
    root = InstallationRoot()
    root.create_fresh()

    # Pre-populate valid configured remotes
    conf_content = (
        "[gdrive]\n"
        "type = drive\n"
        "scope = drive.readonly\n"
        "token = {\"access_token\":\"tok_valid_123\"}\n\n"
        "[ncwebdav]\n"
        "type = webdav\n"
        "vendor = nextcloud\n"
        "url = https://nextcloud.example.local/remote.php/webdav/\n"
        "user = testuser\n"
        "pass = obscured_pass_secret\n"
    )
    root.rclone_conf_path.write_text(conf_content, encoding="utf-8")

    try:
        yield root
    finally:
        SyncExecutor.reset_instance()
        root.cleanup()


@pytest.fixture
def executor(isolated_install: InstallationRoot) -> SyncExecutor:
    """Provide isolated SyncExecutor instance."""
    SyncExecutor.reset_instance()
    return SyncExecutor(
        session_factory=get_db_session,
        rclone_conf_path=isolated_install.rclone_conf_path,
        rclone_bin=isolated_install.fake_rclone.bin_path,
        log_dir=isolated_install.log_dir,
    )


def test_command_builder_strict_fixed_remotes(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify command builder strictly targets fixed endpoints gdrive: and ncwebdav: using snapshot."""
    cfg = Configuration(
        session_factory=get_db_session,
        rclone_conf_path=isolated_install.rclone_conf_path,
    )
    paths_snapshot, perf_snapshot = cfg.create_run_snapshot()

    log_file = isolated_install.log_dir / "test.log"
    cmd = RcloneCommandBuilder.build_sync_command(
        paths=paths_snapshot,
        perf=perf_snapshot,
        rclone_conf_path=isolated_install.rclone_conf_path,
        log_file_path=log_file,
        rclone_bin=str(isolated_install.fake_rclone.bin_path),
    )

    # Validate strict fixed endpoint identities
    assert "copy" in cmd
    assert any(arg.startswith("gdrive:") for arg in cmd)
    assert any(arg.startswith("ncwebdav:") for arg in cmd)
    assert f"--config={isolated_install.rclone_conf_path}" in cmd

    # Check that secrets are not passed as CLI flags
    joined = " ".join(cmd)
    assert "obscured_pass_secret" not in joined
    assert "tok_valid_123" not in joined


def test_manual_run_lifecycle_success(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify end-to-end execution of manual sync: pending -> running -> completed."""
    scenario = FakeRcloneScenario(
        name="sync_success",
        events_to_emit=[
            {
                "level": "info",
                "msg": "Copied (new)",
                "object": "docs/report.pdf",
                "size": 4096,
                "time": "2026-09-13T20:00:00Z",
            },
            {
                "level": "info",
                "msg": "Copied (replaced)",
                "object": "docs/budget.xlsx",
                "size": 8192,
                "time": "2026-09-13T20:00:01Z",
            },
        ],
    )

    isolated_install.fake_rclone.set_scenario(scenario)
    result = executor.trigger_manual_run()
    assert result.accepted is True
    assert result.status == SyncStatus.PENDING
    run_id = result.run_id

    # Verify durable PENDING record existed
    with get_db_session() as db:
        run_record = db.get(Run, run_id)
        assert run_record is not None
        assert run_record.status in (SyncStatus.PENDING, SyncStatus.RUNNING, SyncStatus.COMPLETED)

    # Wait for background execution to complete
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    assert not executor.is_running()

    # Verify terminal state in database
    with get_db_session() as db:
        finished_run = db.get(Run, run_id)
        assert finished_run.status == SyncStatus.COMPLETED
        assert finished_run.finished_at is not None
        assert finished_run.num_added == 1
        assert finished_run.num_updated == 1

        # Verify file events
        events = db.execute(
            select(FileEvent).where(FileEvent.run_id == run_id).order_by(FileEvent.id)
        ).scalars().all()
        assert len(events) == 2
        paths = [e.file_path for e in events]
        assert "docs/report.pdf" in paths
        assert "docs/budget.xlsx" in paths


def test_concurrent_manual_triggers_skipped(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify single-active-run policy: overlapping trigger produces a SKIPPED run."""
    scenario = FakeRcloneScenario(name="cancellation")

    isolated_install.fake_rclone.set_scenario(scenario)
    res1 = executor.trigger_manual_run()
    assert res1.accepted is True
    assert res1.status == SyncStatus.PENDING

    time.sleep(0.1)
    assert executor.is_running()

    # Second trigger should be rejected deterministically as SKIPPED
    res2 = executor.trigger_manual_run()
    assert res2.accepted is False
    assert res2.status == SyncStatus.SKIPPED

    # Verify skipped record in database
    with get_db_session() as db:
        skipped_run = db.get(Run, res2.run_id)
        assert skipped_run is not None
        assert skipped_run.status == SyncStatus.SKIPPED
        assert skipped_run.finished_at is not None

    # Clean up by aborting active run
    executor.request_abort(res1.run_id)
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)


def test_configuration_lease_contention_during_sync(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify configuration mutation is blocked with LeaseError while sync is running."""
    scenario = FakeRcloneScenario(name="cancellation")

    isolated_install.fake_rclone.set_scenario(scenario)
    res = executor.trigger_manual_run()
    assert res.accepted is True
    time.sleep(0.15)
    assert executor.is_running()

    # Attempting to acquire configuration lease must fail
    lease = get_process_lease()
    with pytest.raises(ConfigurationLeaseError):
        with lease.acquire(holder="TestContention", timeout=0.2):
            pass

    # Abort run
    executor.request_abort(res.run_id)
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)


def test_manual_run_failure_terminal_state(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify non-zero exit code produces FAILED status with redacted error message."""
    scenario = FakeRcloneScenario(name="non_zero_exit", exit_code=1)

    isolated_install.fake_rclone.set_scenario(scenario)
    res = executor.trigger_manual_run()
    assert res.accepted is True

    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    with get_db_session() as db:
        failed_run = db.get(Run, res.run_id)
        assert failed_run.status == SyncStatus.FAILED
        assert failed_run.finished_at is not None
        assert "rclone exited with code 1" in (failed_run.message or "")


def test_manual_run_abort_produces_aborted_terminal_state(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify user stop request produces ABORTED terminal state."""
    scenario = FakeRcloneScenario(name="cancellation")

    isolated_install.fake_rclone.set_scenario(scenario)
    res = executor.trigger_manual_run()
    assert res.accepted is True
    time.sleep(0.15)
    assert executor.is_running()

    abort_res = executor.request_abort(res.run_id)
    assert abort_res.requested is True

    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    with get_db_session() as db:
        aborted_run = db.get(Run, res.run_id)
        assert aborted_run.status == SyncStatus.ABORTED
        assert aborted_run.finished_at is not None
        assert "aborted" in (aborted_run.message or "").lower()


def test_active_run_snapshot_and_log_tailing(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify ActiveRunSnapshot updates during run and log tailing streams entries."""
    scenario = FakeRcloneScenario(
        name="sync_success",
        events_to_emit=[
            {
                "level": "info",
                "msg": "Copied (new)",
                "object": "file1.txt",
                "size": 100,
                "time": "2026-09-13T20:00:00Z",
            }
        ],
    )

    isolated_install.fake_rclone.set_scenario(scenario)
    res = executor.trigger_manual_run()
    assert res.accepted is True

    # Check snapshot
    snap = executor.get_active_snapshot()
    assert snap is not None
    assert snap.run_id == res.run_id

    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    # Tail logs
    logs, next_line, is_live = executor.tail_log_file(res.run_id, since_line=0, limit=50)
    assert next_line >= len(logs)
    assert not is_live


def test_api_manual_trigger_route_integration(isolated_install: InstallationRoot):
    """Verify POST /runs routes through SyncExecutor creating durable run and returning 200 with run_id."""
    from fastapi.testclient import TestClient
    from app.api.main import app

    scenario = FakeRcloneScenario(
        name="sync_success",
        events_to_emit=[
            {
                "level": "info",
                "msg": "Copied (new)",
                "object": "test.txt",
                "size": 100,
                "time": "2026-09-13T20:00:00Z",
            }
        ],
    )
    isolated_install.fake_rclone.set_scenario(scenario)

    client = TestClient(app)
    response = client.post("/runs")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "data" in data
    assert "run_id" in data["data"]
    run_id = data["data"]["run_id"]

    # Verify run exists in database
    with get_db_session() as db:
        run_obj = db.get(Run, run_id)
        assert run_obj is not None


def test_secret_redaction_in_diagnostics_and_logs(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Verify credentials and tokens are redacted from error messages and logs."""
    scenario = FakeRcloneScenario(
        name="malformed_output",
        exit_code=1,
        malformed_log_lines=[
            "Error: access_token=\"secret_token_val_12345\" failed",
            "Error: --pass=\"my_super_secret_pw\" authentication failure",
        ],
    )
    isolated_install.fake_rclone.set_scenario(scenario)

    res = executor.trigger_manual_run()
    assert res.accepted is True

    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    with get_db_session() as db:
        failed_run = db.get(Run, res.run_id)
        assert failed_run.status == SyncStatus.FAILED
        assert "secret_token_val_12345" not in (failed_run.message or "")
        assert "my_super_secret_pw" not in (failed_run.message or "")

    logs, _, _ = executor.tail_log_file(res.run_id, since_line=0, limit=50)
    for log in logs:
        assert "secret_token_val_12345" not in log.get("message", "")
        assert "my_super_secret_pw" not in log.get("message", "")
