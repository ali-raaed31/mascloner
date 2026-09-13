"""VM topology and storage preflight checks.

Enforces ADR 0006 requirements:
- Exactly one control process on one VM (PID lease).
- Local persistent block storage verification (detects and warns against network filesystems like NFS/SMB).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Known network/remote filesystem magic numbers / identifiers
NETWORK_FS_TYPES = {
    "nfs",
    "nfs4",
    "cifs",
    "smb",
    "smbfs",
    "sshfs",
    "fuse.sshfs",
    "glusterfs",
    "ceph",
    "gpfs",
}


class TopologyError(RuntimeError):
    """Raised when an unsupported execution topology (e.g. multiple control processes) is detected."""


class PidLease:
    """Manages the process lockfile lifecycle."""

    def __init__(self, pid_file: Path, pid: int) -> None:
        self.pid_file = Path(pid_file).resolve()
        self.pid = pid
        self.is_held = True

    def release(self) -> None:
        """Release and remove the PID file if held by this process."""
        if not self.is_held:
            return
        try:
            if self.pid_file.exists():
                stored_pid_str = self.pid_file.read_text(encoding="utf-8").strip()
                if stored_pid_str.isdigit() and int(stored_pid_str) == self.pid:
                    self.pid_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Failed to remove PID file %s: %s", self.pid_file, exc)
        finally:
            self.is_held = False

    def __enter__(self) -> PidLease:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


def _is_process_alive(pid: int) -> bool:
    """Check whether a process with given PID is alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but belongs to another user
        return True
    except OSError:
        return False


def acquire_pid_lease(pid_file: Path) -> PidLease:
    """Acquire the single-control-process PID lease.

    Raises TopologyError if an active control process is already running.
    Reclaims stale PID files left by dead processes cleanly.
    """
    path = Path(pid_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    current_pid = os.getpid()

    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content.isdigit():
                existing_pid = int(content)
                if existing_pid != current_pid and _is_process_alive(existing_pid):
                    raise TopologyError(
                        f"Unsupported topology: Another MasCloner control process is already running "
                        f"(PID: {existing_pid}). ADR 0006 permits only one control process on one VM."
                    )
                logger.info("Reclaiming stale PID file %s (previous PID %d is not alive)", path, existing_pid)
        except TopologyError:
            raise
        except Exception as exc:
            logger.warning("Error reading existing PID file %s: %s", path, exc)

    # Write current PID with restrictive permissions (0600)
    temp_pid = path.with_name(f"{path.name}.tmp.{current_pid}")
    try:
        with open(temp_pid, "w", encoding="utf-8") as f:
            f.write(f"{current_pid}\n")
        os.chmod(temp_pid, 0o600)
        temp_pid.replace(path)
        os.chmod(path, 0o600)
    finally:
        if temp_pid.exists():
            try:
                temp_pid.unlink()
            except OSError:
                pass

    logger.info("Acquired single-process PID lease for PID %d at %s", current_pid, path)
    return PidLease(path, current_pid)


def _get_filesystem_type(path: Path) -> str:
    """Determine filesystem type for a path from /proc/mounts if available on Linux."""
    try:
        resolved = path.resolve()
        best_mount = ""
        best_fstype = "ext4"  # Default assumption for Linux local storage

        if Path("/proc/mounts").exists():
            with open("/proc/mounts", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point = parts[1]
                        fstype = parts[2]
                        if str(resolved).startswith(mount_point) and len(mount_point) > len(best_mount):
                            best_mount = mount_point
                            best_fstype = fstype

        return best_fstype
    except Exception as exc:
        logger.debug("Could not inspect /proc/mounts: %s", exc)
        return "unknown"


def check_storage_suitability(path: Path) -> Dict[str, Any]:
    """Verify that storage is suitable for SQLite (local block storage vs network mount)."""
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    fstype = _get_filesystem_type(target).lower()

    if any(net_fs in fstype for net_fs in NETWORK_FS_TYPES):
        warning = (
            f"Database location {target} appears to reside on network-mounted filesystem '{fstype}'. "
            f"SQLite in WAL mode requires local persistent block storage (Hyperdisk/Persistent Disk). "
            f"Network mounts can cause locking issues, silent corruption, or high latency (ADR 0006)."
        )
        logger.warning(warning)
        return {
            "path": str(target),
            "fstype": fstype,
            "is_suitable": False,
            "warning": warning,
        }

    return {
        "path": str(target),
        "fstype": fstype,
        "is_suitable": True,
        "warning": None,
    }
