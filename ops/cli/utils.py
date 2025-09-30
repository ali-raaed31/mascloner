"""Utility functions for CLI operations."""
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console

console = Console()


def require_root():
    """Check if running as root, exit if not."""
    if os.geteuid() != 0:
        console.print("[red]✗ This command must be run as root (use sudo)[/red]")
        raise SystemExit(1)


def get_install_dir() -> Path:
    """Get the MasCloner installation directory."""
    install_dir = os.environ.get("INSTALL_DIR", "/srv/mascloner")
    return Path(install_dir)


def get_backup_dir() -> Path:
    """Get the backup directory."""
    backup_dir = os.environ.get("BACKUP_DIR", "/var/backups/mascloner")
    return Path(backup_dir)


def get_mascloner_user() -> str:
    """Get the MasCloner system user."""
    return os.environ.get("MASCLONER_USER", "mascloner")


def get_git_repo() -> str:
    """Get the Git repository URL."""
    return os.environ.get("GIT_REPO", "https://github.com/ali-raaed31/mascloner.git")


def run_command(
    cmd: List[str], check: bool = True, capture: bool = True
) -> Tuple[int, str, str]:
    """
    Run a shell command and return the result.
    
    Args:
        cmd: Command and arguments as a list
        check: Raise exception on non-zero exit
        capture: Capture stdout/stderr
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=check,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout or "", e.stderr or ""


def check_systemd_service(service_name: str) -> Tuple[bool, str]:
    """
    Check if a systemd service exists and its status.
    
    Returns:
        Tuple of (is_active, status_string)
    """
    # Check if service file exists
    service_file = Path(f"/etc/systemd/system/{service_name}.service")
    if not service_file.exists():
        return False, "not_installed"

    # Check if service is active
    exit_code, _, _ = run_command(
        ["systemctl", "is-active", "--quiet", f"{service_name}.service"],
        check=False,
        capture=True,
    )

    if exit_code == 0:
        return True, "active"

    # Check if failed
    exit_code, _, _ = run_command(
        ["systemctl", "is-failed", "--quiet", f"{service_name}.service"],
        check=False,
        capture=True,
    )

    if exit_code == 0:
        return False, "failed"

    return False, "stopped"


def stop_service(service_name: str) -> bool:
    """Stop a systemd service."""
    is_active, status = check_systemd_service(service_name)

    if status == "not_installed":
        return True  # Nothing to stop

    if not is_active and status == "stopped":
        return True  # Already stopped

    exit_code, _, _ = run_command(
        ["systemctl", "stop", f"{service_name}.service"], check=False
    )

    return exit_code == 0


def start_service(service_name: str) -> bool:
    """Start a systemd service."""
    _, status = check_systemd_service(service_name)

    if status == "not_installed":
        return True  # Nothing to start

    exit_code, _, _ = run_command(
        ["systemctl", "start", f"{service_name}.service"], check=False
    )

    return exit_code == 0


def get_service_logs(service_name: str, lines: int = 20) -> List[str]:
    """Get recent logs from a systemd service."""
    exit_code, stdout, _ = run_command(
        [
            "journalctl",
            "-u",
            f"{service_name}.service",
            "--no-pager",
            "-l",
            "--since",
            "5 minutes ago",
            "-n",
            str(lines),
        ],
        check=False,
    )

    if exit_code == 0:
        return stdout.strip().split("\n")
    return []


def create_backup(install_dir: Path, backup_dir: Path) -> Optional[Path]:
    """
    Create a backup of the MasCloner installation.
    
    Returns:
        Path to backup file, or None if failed
    """
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"mascloner_pre_update_{timestamp}.tar.gz"
    backup_path = backup_dir / backup_name

    try:
        with tarfile.open(backup_path, "w:gz") as tar:
            # Backup critical directories and files
            for item in ["data", "etc", ".env", "app", "requirements.txt"]:
                item_path = install_dir / item
                if item_path.exists():
                    tar.add(
                        item_path,
                        arcname=item,
                        filter=lambda x: x
                        if "__pycache__" not in x.name and not x.name.endswith(".pyc")
                        else None,
                    )

        return backup_path
    except Exception as e:
        console.print(f"[red]Failed to create backup: {e}[/red]")
        return None


def get_file_size_human(path: Path) -> str:
    """Get human-readable file size."""
    size = path.stat().st_size
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def compare_directories(dir1: Path, dir2: Path) -> Tuple[List[str], List[str], List[str]]:
    """
    Compare two directories and return differences.
    
    Returns:
        Tuple of (added, removed, modified) file lists
    """
    added = []
    removed = []
    modified = []

    # Get file lists
    files1 = set()
    files2 = set()

    if dir1.exists():
        for item in dir1.rglob("*"):
            if item.is_file() and "__pycache__" not in str(item):
                files1.add(item.relative_to(dir1))

    if dir2.exists():
        for item in dir2.rglob("*"):
            if item.is_file() and "__pycache__" not in str(item):
                files2.add(item.relative_to(dir2))

    # Find added and removed
    added = list(files2 - files1)
    removed = list(files1 - files2)

    # Find modified (simplified - just check size)
    common = files1 & files2
    for file in common:
        file1 = dir1 / file
        file2 = dir2 / file
        if file1.stat().st_size != file2.stat().st_size:
            modified.append(str(file))

    return (
        [str(f) for f in added],
        [str(f) for f in removed],
        modified,
    )


def get_current_version(install_dir: Path) -> str:
    """Get current installed version."""
    # Try to get from git
    git_dir = install_dir / ".git"
    if git_dir.exists():
        exit_code, stdout, _ = run_command(
            ["git", "-C", str(install_dir), "describe", "--tags", "--always"],
            check=False,
        )
        if exit_code == 0:
            return stdout.strip()

    # Try to get from version file
    version_file = install_dir / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()

    return "unknown"


def check_http_endpoint(url: str, timeout: int = 10) -> bool:
    """Check if an HTTP endpoint is responding."""
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False
