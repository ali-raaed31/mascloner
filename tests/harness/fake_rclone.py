"""Fake rclone executable controller and scenario manager.

Simulates rclone CLI operations without real network or cloud interactions.
Supports success, non-zero exits, timeouts, cancellation, malformed logs,
and token/config mutations.
"""

from __future__ import annotations

import configparser
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class FakeRcloneScenario:
    """Configurable scenario for FakeRclone."""

    name: str = "success"  # success, non_zero_exit, timeout, cancellation, malformed_output, token_mutation
    exit_code: int = 0
    sleep_seconds: float = 0.0
    stdout_override: Optional[str] = None
    stderr_override: Optional[str] = None
    events_to_emit: List[Dict[str, Any]] = field(default_factory=list)
    malformed_log_lines: List[str] = field(default_factory=list)
    mutate_config: Optional[Dict[str, Dict[str, str]]] = None
    remotes_override: Optional[List[str]] = None
    directories_override: Optional[List[str]] = None
    missing_paths: List[str] = field(default_factory=list)
    failing_remotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FakeRcloneScenario:
        return cls(**data)


class FakeRcloneController:
    """Controller for configuring the fake rclone executable and tracking invocations."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.control_file = root_dir / "fake_rclone_control.json"
        self.invocations_file = root_dir / "fake_rclone_invocations.json"
        self.bin_dir = root_dir / "bin"
        self.bin_path = self.bin_dir / "rclone"
        self.set_scenario(FakeRcloneScenario(name="success"))

    def install(self) -> Path:
        """Install the fake rclone executable in bin_dir."""
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        py_exe = sys.executable
        script_code = f"""#!{py_exe}
import sys
from pathlib import Path

repo_root = Path({repr(str(REPO_ROOT))})
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from tests.harness.fake_rclone import run_fake_rclone_cli

if __name__ == "__main__":
    control_file = Path({repr(str(self.control_file))})
    invocations_file = Path({repr(str(self.invocations_file))})
    sys.exit(run_fake_rclone_cli(sys.argv, control_file, invocations_file))
"""
        self.bin_path.write_text(script_code, encoding="utf-8")
        self.bin_path.chmod(0o755)
        return self.bin_path

    def set_scenario(self, scenario: FakeRcloneScenario) -> None:
        """Write scenario to the control file."""
        self.control_file.parent.mkdir(parents=True, exist_ok=True)
        self.control_file.write_text(json.dumps(scenario.to_dict(), indent=2), encoding="utf-8")

    def get_invocations(self) -> List[Dict[str, Any]]:
        """Read all recorded invocations."""
        if not self.invocations_file.exists():
            return []
        invocations = []
        try:
            with open(self.invocations_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        invocations.append(json.loads(line))
        except Exception:
            pass
        return invocations

    def clear_invocations(self) -> None:
        """Clear recorded invocations."""
        if self.invocations_file.exists():
            self.invocations_file.unlink()


def _extract_flag_value(argv: List[str], flag: str) -> Optional[str]:
    """Extract value for --flag=value or --flag value."""
    for i, arg in enumerate(argv):
        if arg.startswith(f"{flag}="):
            return arg[len(flag) + 1 :]
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
    return None


def run_fake_rclone_cli(
    argv: List[str],
    control_file: Optional[Path] = None,
    invocations_file: Optional[Path] = None,
) -> int:
    """Execute simulated rclone logic matching the command line arguments."""
    # Resolve control & invocations files
    if control_file is None:
        env_ctrl = os.environ.get("FAKE_RCLONE_CONTROL_FILE")
        if env_ctrl:
            control_file = Path(env_ctrl)

    if invocations_file is None:
        env_inv = os.environ.get("FAKE_RCLONE_INVOCATIONS_FILE")
        if env_inv:
            invocations_file = Path(env_inv)

    # Load scenario
    scenario = FakeRcloneScenario()
    if control_file and control_file.exists():
        try:
            scenario = FakeRcloneScenario.from_dict(json.loads(control_file.read_text(encoding="utf-8")))
        except Exception:
            pass

    # Record invocation
    if invocations_file:
        invocations_file.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "argv": argv,
            "cwd": os.getcwd(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scenario": scenario.name,
        }
        with open(invocations_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    args = argv[1:]
    if not args:
        print("rclone: fake mock executable")
        return 0

    config_path = _extract_flag_value(args, "--config")
    log_file_path = _extract_flag_value(args, "--log-file")

    pos_args: List[str] = []
    skip_next = False
    for i, a in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if a.startswith("--"):
            if "=" not in a and i + 1 < len(args) and not args[i + 1].startswith("-"):
                skip_next = True
            continue
        if a.startswith("-"):
            continue
        pos_args.append(a)

    subcommand = pos_args[0] if pos_args else ""

    if subcommand in ("about", "lsd") and len(pos_args) > 1:
        if pos_args[1].split(":", 1)[0] in scenario.failing_remotes:
            sys.stderr.write("remote unavailable\n")
            return 3

    # If sleep requested
    if scenario.sleep_seconds > 0:
        time.sleep(scenario.sleep_seconds)

    # Specific subcommands
    if subcommand == "version":
        sys.stdout.write(
            "rclone v1.68.0\n"
            "- os/version: ubuntu 24.04\n"
            "- os/kernel: 6.8.0\n"
            "- os/type: linux\n"
            "- os/arch: amd64\n"
            "- go/version: go1.22.5\n"
        )
        return 0

    if scenario.exit_code != 0 and subcommand not in ("version", "copy"):
        if scenario.stderr_override:
            sys.stderr.write(scenario.stderr_override)
        elif not scenario.stdout_override:
            sys.stderr.write(f"Fake rclone error: exit code {scenario.exit_code}\n")
        if scenario.stdout_override:
            sys.stdout.write(scenario.stdout_override)
        return scenario.exit_code

    if subcommand == "listremotes":
        if scenario.remotes_override is not None:
            for r in scenario.remotes_override:
                sys.stdout.write(f"{r}:\n")
            return 0
        if config_path and Path(config_path).exists():
            cp = configparser.ConfigParser()
            cp.read(config_path)
            for section in cp.sections():
                sys.stdout.write(f"{section}:\n")
        else:
            sys.stdout.write("gdrive:\nncwebdav:\n")
        return 0

    if subcommand == "lsd":
        dirs = scenario.directories_override or ["Documents", "Photos", "Backups"]
        for d in dirs:
            sys.stdout.write(f"          -1 2026-09-01 12:00:00        -1 {d}\n")
        return 0

    if subcommand == "lsjson" and "--stat" in args:
        selected = pos_args[1] if len(pos_args) > 1 else ""
        if selected in scenario.missing_paths:
            sys.stderr.write("directory not found\n")
            return 3
        sys.stdout.write(json.dumps({"Path": selected, "IsDir": True, "Size": -1}))
        return 0

    if subcommand == "lsjson":
        dirs = scenario.directories_override or ["Documents", "Photos", "Backups"]
        data = [
            {
                "Path": d,
                "Name": d,
                "Size": -1,
                "MimeType": "inode/directory",
                "ModTime": "2026-09-01T12:00:00.000000Z",
                "IsDir": True,
            }
            for d in dirs
        ]
        sys.stdout.write(json.dumps(data))
        return 0

    if subcommand == "size":
        sys.stdout.write(json.dumps({"count": 5, "bytes": 10485760}))
        return 0

    if subcommand == "obscure":
        pwd = pos_args[1] if len(pos_args) > 1 else ""
        sys.stdout.write(f"obscured_{pwd}\n")
        return 0

    if subcommand == "about":
        sys.stdout.write("Total: 107374182400\nUsed: 10737418240\nFree: 96636764160\n")
        return 0

    if subcommand == "config":
        action = pos_args[1] if len(pos_args) > 1 else ""
        if action == "dump":
            dump_data: Dict[str, Any] = {}
            if config_path and Path(config_path).exists():
                cp = configparser.ConfigParser()
                cp.read(config_path)
                for section in cp.sections():
                    dump_data[section] = dict(cp[section])
            sys.stdout.write(json.dumps(dump_data))
            return 0
        if action == "show":
            remote = pos_args[2] if len(pos_args) > 2 else ""
            if config_path and Path(config_path).exists():
                cp = configparser.ConfigParser()
                cp.read(config_path)
                if cp.has_section(remote):
                    for k, v in cp[remote].items():
                        sys.stdout.write(f"{k} = {v}\n")
            return 0
        if action in ("create", "update"):
            remote = pos_args[2] if len(pos_args) > 2 else "temp_remote"
            remote_type = pos_args[3] if len(pos_args) > 3 else "drive"
            if config_path:
                p = Path(config_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                cp = configparser.ConfigParser()
                if p.exists():
                    cp.read(str(p))
                if not cp.has_section(remote):
                    cp.add_section(remote)
                cp.set(remote, "type", remote_type)
                for item in pos_args[4:]:
                    if "=" in item:
                        k, v = item.split("=", 1)
                        cp.set(remote, k, v)
                with open(str(p), "w") as f:
                    cp.write(f)
            return 0
        if action == "delete":
            remote = pos_args[2] if len(pos_args) > 2 else ""
            if config_path and Path(config_path).exists():
                cp = configparser.ConfigParser()
                cp.read(config_path)
                if cp.has_section(remote):
                    cp.remove_section(remote)
                    with open(config_path, "w") as f:
                        cp.write(f)
            return 0
        if action == "reconnect":
            return 0

    # Handling copy command
    if subcommand == "copy":
        if scenario.name == "timeout":
            time.sleep(30.0)
            return 0

        if scenario.name == "cancellation":
            cancelled = [False]

            def _handle_term(signum, frame):
                cancelled[0] = True

            signal.signal(signal.SIGTERM, _handle_term)
            if log_file_path:
                ready_file = Path(log_file_path).with_suffix(".ready")
                ready_file.parent.mkdir(parents=True, exist_ok=True)
                ready_file.write_text("ready", encoding="utf-8")

            start_t = time.time()
            while not cancelled[0] and (time.time() - start_t < 15.0):
                time.sleep(0.05)

            if log_file_path:
                p = Path(log_file_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file_path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "level": "notice",
                                "msg": "Interrupt received, stopping gracefully",
                                "time": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        + "\n"
                    )
            return 143

        if scenario.name == "malformed_output":
            if log_file_path:
                p = Path(log_file_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file_path, "w", encoding="utf-8") as f:
                    for line in scenario.malformed_log_lines or [
                        "INVALID_NON_JSON_LINE_ERR",
                        "{'bad_json': true,",
                        "Transferred: corrupted stats line",
                    ]:
                        f.write(line + "\n")
            sys.stdout.write("CORRUPTED RAW STDOUT\n")
            return scenario.exit_code

        if scenario.name == "non_zero_exit":
            if log_file_path:
                p = Path(log_file_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(log_file_path, "w", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "level": "error",
                                "msg": "Failed to copy: remote directory not found",
                                "object": "sync_error",
                                "time": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        + "\n"
                    )
            sys.stderr.write("Fatal error: remote directory not found\n")
            return scenario.exit_code if scenario.exit_code != 0 else 1

        # Token mutation scenario
        if scenario.name == "token_mutation" or scenario.mutate_config:
            if config_path and Path(config_path).exists():
                cp = configparser.ConfigParser()
                cp.read(config_path)
                mutations = scenario.mutate_config or {
                    "gdrive": {
                        "token": json.dumps(
                            {
                                "access_token": "mutated_refreshed_token_val_999",
                                "token_type": "Bearer",
                                "refresh_token": "valid_refresh_token_abc",
                                "expiry": "2026-12-31T23:59:59Z",
                            }
                        )
                    }
                }
                for sec, vals in mutations.items():
                    if not cp.has_section(sec):
                        cp.add_section(sec)
                    for k, v in vals.items():
                        cp.set(sec, k, v)
                with open(config_path, "w") as f:
                    cp.write(f)

        # Standard successful sync events
        if log_file_path:
            p = Path(log_file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            events = scenario.events_to_emit or [
                {
                    "level": "info",
                    "msg": "Copied (new)",
                    "object": "file_alpha.docx",
                    "size": 1024,
                    "time": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "level": "info",
                    "msg": "Copied (replaced)",
                    "object": "file_beta.xlsx",
                    "size": 2048,
                    "time": datetime.now(timezone.utc).isoformat(),
                },
                {
                    "level": "notice",
                    "msg": "Transferred: 3072 / 3072, 2 files, 0 errors",
                    "time": datetime.now(timezone.utc).isoformat(),
                },
            ]
            with open(log_file_path, "w", encoding="utf-8") as f:
                for evt in events:
                    f.write(json.dumps(evt) + "\n")

        return scenario.exit_code

    if scenario.stdout_override:
        sys.stdout.write(scenario.stdout_override)
    if scenario.stderr_override:
        sys.stderr.write(scenario.stderr_override)
    return scenario.exit_code
