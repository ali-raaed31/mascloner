"""Tests validating the characterization harness itself.

Verifies:
1. Complete isolated installation creation and teardown without touching live environment.
2. Fake process coverage: success, non-zero exit, timeout, cancellation, malformed output, config/token mutation.
3. Secret leakage detection fails when deliberate secrets appear in diagnostics.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
import pytest

from tests.harness.assertions import assert_no_secrets_leaked, scan_for_secrets
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset


def test_isolated_installation_lifecycle():
    """Verify an isolated installation creates its root and cleans up without touching caller env."""
    home_rclone_conf = Path.home() / ".config" / "rclone" / "rclone.conf"
    home_mtime_before = home_rclone_conf.stat().st_mtime if home_rclone_conf.exists() else None

    install = InstallationRoot()
    install.create_fresh()

    base_dir = install.base_dir
    assert base_dir.exists()
    assert (base_dir / "data" / "mascloner.db").exists()
    assert (base_dir / "etc" / "rclone.conf").exists()
    assert (base_dir / "bin" / "rclone").exists()
    assert os.access(base_dir / "bin" / "rclone", os.X_OK)

    # Check caller home directory remains untouched
    if home_rclone_conf.exists():
        assert home_rclone_conf.stat().st_mtime == home_mtime_before
    else:
        assert not home_rclone_conf.exists()

    install.cleanup()
    assert not base_dir.exists()


def test_fake_rclone_success_scenario():
    """Verify fake rclone handles success copy and emits valid JSON logs."""
    install = InstallationRoot()
    install.create_fresh()
    rclone_bin = install.bin_dir / "rclone"
    log_file = install.log_dir / "test_success.log"

    install.fake_rclone.set_scenario(FakeRcloneScenario(name="success"))

    proc = subprocess.run(
        [
            str(rclone_bin),
            "copy",
            "gdrive:src",
            "ncwebdav:dest",
            f"--config={install.rclone_conf_path}",
            f"--log-file={log_file}",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Copied (new)" in content
    assert "Transferred" in content

    # Check recorded invocations
    invocations = install.fake_rclone.get_invocations()
    assert len(invocations) >= 1
    assert invocations[-1]["argv"][1] == "copy"

    install.cleanup()


def test_fake_rclone_nonzero_exit_scenario():
    """Verify fake rclone handles non-zero exit codes and writes error logs."""
    install = InstallationRoot()
    install.create_fresh()
    rclone_bin = install.bin_dir / "rclone"
    log_file = install.log_dir / "test_nonzero.log"

    install.fake_rclone.set_scenario(FakeRcloneScenario(name="non_zero_exit", exit_code=2))

    proc = subprocess.run(
        [
            str(rclone_bin),
            "copy",
            "gdrive:src",
            "ncwebdav:dest",
            f"--config={install.rclone_conf_path}",
            f"--log-file={log_file}",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Failed to copy" in content
    install.cleanup()


def test_fake_rclone_timeout_scenario():
    """Verify fake rclone simulates timeout by sleeping longer than subprocess timeout."""
    install = InstallationRoot()
    install.create_fresh()
    rclone_bin = install.bin_dir / "rclone"

    install.fake_rclone.set_scenario(FakeRcloneScenario(name="timeout", sleep_seconds=5.0))

    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [str(rclone_bin), "copy", "gdrive:src", "ncwebdav:dest"],
            capture_output=True,
            timeout=0.3,
        )
    install.cleanup()


def test_fake_rclone_cancellation_scenario():
    """Verify fake rclone handles SIGTERM cancellation gracefully."""
    install = InstallationRoot()
    install.create_fresh()
    rclone_bin = install.bin_dir / "rclone"
    log_file = install.log_dir / "test_cancel.log"
    ready_file = log_file.with_suffix(".ready")

    install.fake_rclone.set_scenario(FakeRcloneScenario(name="cancellation"))

    proc = subprocess.Popen(
        [
            str(rclone_bin),
            "copy",
            "gdrive:src",
            "ncwebdav:dest",
            f"--config={install.rclone_conf_path}",
            f"--log-file={log_file}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for child process to be ready and listening for signals
    for _ in range(50):
        if ready_file.exists():
            break
        time.sleep(0.05)

    proc.terminate()  # Sends SIGTERM
    ret = proc.wait(timeout=5.0)

    assert ret in (143, 0, -signal.SIGTERM)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Interrupt received" in content
    install.cleanup()


def test_fake_rclone_malformed_output_scenario():
    """Verify fake rclone handles malformed/corrupted logs."""
    install = InstallationRoot()
    install.create_fresh()
    rclone_bin = install.bin_dir / "rclone"
    log_file = install.log_dir / "test_malformed.log"

    install.fake_rclone.set_scenario(
        FakeRcloneScenario(
            name="malformed_output",
            malformed_log_lines=["NOT_VALID_JSON_1", "CORRUPT_LINE_2"],
        )
    )

    proc = subprocess.run(
        [
            str(rclone_bin),
            "copy",
            "gdrive:src",
            "ncwebdav:dest",
            f"--config={install.rclone_conf_path}",
            f"--log-file={log_file}",
        ],
        capture_output=True,
        text=True,
    )

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "NOT_VALID_JSON_1" in content
    assert "CORRUPT_LINE_2" in content
    install.cleanup()


def test_fake_rclone_token_mutation_scenario():
    """Verify fake rclone can simulate OAuth token refresh during a sync."""
    install = InstallationRoot()
    install.create_fresh()
    rclone_bin = install.bin_dir / "rclone"
    log_file = install.log_dir / "test_token_mutation.log"

    install.fake_rclone.set_scenario(FakeRcloneScenario(name="token_mutation"))

    proc = subprocess.run(
        [
            str(rclone_bin),
            "copy",
            "gdrive:src",
            "ncwebdav:dest",
            f"--config={install.rclone_conf_path}",
            f"--log-file={log_file}",
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    config_text = install.rclone_conf_path.read_text(encoding="utf-8")
    assert "mutated_refreshed_token_val_999" in config_text
    install.cleanup()


def test_secret_leakage_assertion_detection():
    """Verify assert_no_secrets_leaked catches deliberate secrets in diagnostic channels."""
    secret = "SUPER_SECRET_TOKEN_XYZ123"
    non_secret_data = {"status": "ok", "transferred": 100, "safe": "public_data"}

    # Must pass when clean
    assert_no_secrets_leaked(non_secret_data, [secret])

    # Must fail when secret is present in a dictionary
    leaked_dict = {"status": "error", "debug_msg": f"Failed with token {secret}"}
    with pytest.raises(AssertionError) as exc_info:
        assert_no_secrets_leaked(leaked_dict, [secret], context="API Response")
    assert "Security violation" in str(exc_info.value)

    # Must fail when secret is in a log string
    log_channel = f"DEBUG: connecting with {secret} on port 443"
    with pytest.raises(AssertionError) as exc_info:
        assert_no_secrets_leaked(log_channel, [secret], context="rclone stderr")
    assert "Security violation" in str(exc_info.value)
