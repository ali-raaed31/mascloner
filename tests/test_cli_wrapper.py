"""User-facing command behavior for the installed CLI wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.geteuid() == 0, reason="sudo escalation needs a non-root caller")
def test_plain_update_command_elevates_once(tmp_path: Path) -> None:
    sudo = tmp_path / "sudo"
    sudo.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    sudo.chmod(0o755)
    wrapper = Path(__file__).resolve().parents[1] / "ops/scripts/mascloner"
    environment = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", INSTALL_DIR="/srv/mascloner")

    result = subprocess.run(["bash", str(wrapper), "update"], env=environment, capture_output=True, text=True)

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["env", "INSTALL_DIR=/srv/mascloner", str(wrapper), "update"]
