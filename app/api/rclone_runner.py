"""rclone execution and JSON log parsing for MasCloner.

This module provides both synchronous and asynchronous interfaces for rclone operations.
- Sync methods: Used by the APScheduler background thread
- Async methods: Used by FastAPI endpoints for non-blocking I/O
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import config, get_log_dir, get_rclone_conf_path

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


@dataclass
class SyncEvent:
    """Individual file sync event."""

    timestamp: datetime
    action: str  # added, updated, skipped, error, conflict
    file_path: str
    file_size: int
    message: str
    file_hash: Optional[str] = None


@dataclass
class SyncResult:
    """Result of a sync operation."""

    status: str  # success, error, partial, running
    num_added: int = 0
    num_updated: int = 0
    bytes_transferred: int = 0
    errors: int = 0
    events: List[SyncEvent] = field(default_factory=list)
    error_message: Optional[str] = None


class RcloneLogParser:
    """Parser for rclone JSON log output based on official rclone documentation."""

    # Stats pattern for fallback when individual file events aren't available
    STATS_PATTERN = re.compile(
        r"Transferred:\s+(\d+)\s+/\s+(\d+),\s+(\d+)\s+files,\s+(\d+)\s+errors"
    )

    # Map rclone log messages to our action types based on official rclone JSON log format
    ACTION_MAP = {
        # Official rclone JSON log message patterns (exact matches)
        "Copied (new)": "added",
        "Copied (replaced)": "updated",
        "Copied": "added",  # Generic copy
        "Transferred (new)": "added",
        "Transferred (replaced)": "updated",
        "Transferred": "added",
        # Skip operations
        "Skipped": "skipped",
        "Skipping": "skipped",
        # Error operations
        "Can't copy": "error",
        "Failed to copy": "error",
        "ERROR": "error",
    }

    def parse_line(self, line: str) -> Optional[SyncEvent]:
        """Parse a single JSON log line from rclone based on official format."""
        if not line.strip():
            return None

        try:
            obj = json.loads(line.strip())
        except (json.JSONDecodeError, AttributeError):
            # Not a JSON line, might be stats or other output
            return None

        # Official rclone JSON log format fields
        level = obj.get("level", "").upper()
        msg = obj.get("msg", "")
        file_path = obj.get("object", "")  # Official field name for file path
        file_size = int(obj.get("size", 0))
        timestamp_str = obj.get("time", "")

        # Parse timestamp if available
        timestamp = _utc_now()
        if timestamp_str:
            try:
                # Handle rclone's timestamp format: "2024-01-05T12:45:54.986126-05:00"
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                pass  # Use current time if parsing fails

        # Debug logging for troubleshooting
        if file_path:  # Only log if there's a file path (actual file operations)
            logger.debug(
                "Parsing rclone log: level=%s, msg='%s', object='%s', size=%d",
                level,
                msg,
                file_path,
                file_size,
            )

        # Determine action from message content
        action = None

        # Check for error level first
        if level == "ERROR":
            action = "error"
        else:
            # Look for action indicators in message (exact match for official patterns)
            for key, val in self.ACTION_MAP.items():
                if key in msg:  # Exact match for official rclone messages
                    action = val
                    logger.debug("Matched action '%s' -> '%s' for file: %s", key, val, file_path)
                    break

        # Skip if no recognizable action
        if not action:
            if file_path:  # Only log if there was a file path
                logger.debug("No action matched for file: %s, msg: '%s'", file_path, msg)
            return None

        # Check for conflict scenarios
        if "already exists" in msg.lower() or "conflict" in msg.lower():
            action = "conflict"

        return SyncEvent(
            timestamp=timestamp,
            action=action,
            file_path=file_path,
            file_size=file_size,
            message=msg,
            file_hash=obj.get("hash"),
        )

    def parse_stats_line(self, line: str) -> Optional[Dict[str, int]]:
        """Parse rclone stats output line as fallback."""
        match = self.STATS_PATTERN.search(line)
        if match:
            transferred, total, files, errors = match.groups()
            return {
                "transferred": int(transferred),
                "total": int(total),
                "files": int(files),
                "errors": int(errors),
            }
        return None


class RcloneRunner:
    """Execute rclone operations and parse results.

    Provides both synchronous and asynchronous methods:
    - Sync methods (run_sync, test_connection, etc.): For scheduler/background use
    - Async methods (run_sync_async, test_connection_async, etc.): For FastAPI endpoints
    """

    def __init__(self) -> None:
        self.parser = RcloneLogParser()
        if config:
            self.rclone_config = config.get_rclone_config()
        else:
            # Fallback defaults
            self.rclone_config = {
                "transfers": 8,
                "checkers": 16,
                "tpslimit": 25,
                "tpslimit_burst": 100,
                "bwlimit": "0",
                "drive_export": "docx,xlsx,pptx",
                "log_level": "INFO",
                "stats_interval": "60s",
                "buffer_size": "32Mi",
                "drive_chunk_size": "64M",
                "drive_upload_cutoff": "128M",
                "fast_list": False,
            }
        self._remote_type_cache: Dict[str, Optional[str]] = {}

    def build_rclone_command(
        self,
        src: str,
        dest: str,
        log_file: str,
        additional_flags: Optional[List[str]] = None,
    ) -> List[str]:
        """Build rclone command with standard flags for MasCloner."""
        rclone_conf = get_rclone_conf_path()

        base_cmd = [
            "rclone",
            "copy",
            src,
            dest,
            f"--config={rclone_conf}",
            f"--log-file={log_file}",
            "--use-json-log",
            f"--log-level={self.rclone_config['log_level']}",
            "--stats-log-level=NOTICE",
            f"--stats={self.rclone_config.get('stats_interval', '60s')}",
            "--stats-one-line",
            f"--checkers={self.rclone_config['checkers']}",
            f"--transfers={self.rclone_config['transfers']}",
            f"--tpslimit={self.rclone_config['tpslimit']}",
            f"--bwlimit={self.rclone_config['bwlimit']}",
            f"--buffer-size={self.rclone_config.get('buffer_size', '32Mi')}",
            f"--retries={self.rclone_config.get('retries', 5)}",
            f"--retries-sleep={self.rclone_config.get('retries_sleep', '10s')}",
            f"--low-level-retries={self.rclone_config.get('low_level_retries', 10)}",
            f"--timeout={self.rclone_config.get('timeout', '5m')}",
            # Google Drive specific flags
            f"--drive-export-formats={self.rclone_config['drive_export']}",
            "--drive-shared-with-me",
            "--drive-skip-shortcuts",
        ]

        if self.rclone_config.get("tpslimit_burst"):
            base_cmd.append(f"--tpslimit-burst={self.rclone_config['tpslimit_burst']}")
        if self.rclone_config.get("fast_list"):
            base_cmd.append("--fast-list")
        if self.rclone_config.get("drive_chunk_size"):
            base_cmd.append(f"--drive-chunk-size={self.rclone_config['drive_chunk_size']}")
        if self.rclone_config.get("drive_upload_cutoff"):
            base_cmd.append(f"--drive-upload-cutoff={self.rclone_config['drive_upload_cutoff']}")

        if additional_flags:
            base_cmd.extend(additional_flags)

        return base_cmd

    # =========================================================================
    # SYNCHRONOUS METHODS (for scheduler/background thread)
    # =========================================================================

    def run_sync(
        self,
        gdrive_remote: str,
        gdrive_src: str,
        nc_remote: str,
        nc_dest_path: str,
        dry_run: bool = False,
    ) -> SyncResult:
        """Execute sync operation synchronously (for scheduler use)."""
        result = SyncResult(status="running")

        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"sync-{timestamp}.log"

        gdrive_src = gdrive_src.strip() if gdrive_src else ""
        nc_dest_path = nc_dest_path.strip() if nc_dest_path else ""

        gdrive_src_clean = gdrive_src.lstrip("/")
        src = f"{gdrive_remote}:{gdrive_src_clean}"
        dest = f"{nc_remote}:{nc_dest_path.rstrip('/')}/"

        logger.info("Starting sync: %s -> %s", src, dest)

        try:
            cmd = self.build_rclone_command(src, dest, str(log_file))

            if dry_run:
                cmd.append("--dry-run")
                logger.info("Running in dry-run mode")

            logger.info("Executing: %s", " ".join(cmd))

            result = self._execute_rclone_sync(cmd, str(log_file))

            logger.info("Sync completed with status: %s", result.status)
            logger.info(
                "Files: %d added, %d updated, %d errors",
                result.num_added,
                result.num_updated,
                result.errors,
            )

            return result

        except Exception as e:
            logger.error("Sync operation failed: %s", e)
            result.status = "error"
            result.error_message = str(e)
            return result

    def _execute_rclone_sync(self, cmd: List[str], log_file: str) -> SyncResult:
        """Execute rclone command synchronously and parse output."""
        result = SyncResult(status="running")
        lightweight_events = os.getenv("MASCLONER_LIGHTWEIGHT_EVENTS", "0").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        try:
            logger.info("Command list has %d elements", len(cmd))
            logger.debug("Command elements [0-5]: %s", [repr(arg) for arg in cmd[:6]])

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            return_code = process.wait()

            if return_code == 0:
                result.status = "success"
            elif result.errors > 0:
                result.status = "partial"
            else:
                result.status = "error"

            logger.info("rclone exited with code: %d", return_code)

            self._parse_log_file(log_file, result, lightweight_events)

            logger.info(
                "Final result: %d added, %d updated, %d errors, %d bytes, %d events",
                result.num_added,
                result.num_updated,
                result.errors,
                result.bytes_transferred,
                len(result.events),
            )

        except subprocess.SubprocessError as e:
            logger.error("rclone subprocess error: %s", e)
            result.status = "error"
            result.error_message = str(e)
        except Exception as e:
            logger.error("Unexpected error during rclone execution: %s", e)
            result.status = "error"
            result.error_message = str(e)

        return result

    def _parse_log_file(
        self, log_file: str, result: SyncResult, lightweight_events: bool
    ) -> None:
        """Parse rclone log file and update result."""
        if not os.path.exists(log_file):
            logger.warning("Log file not found: %s", log_file)
            return

        logger.info("Parsing log file: %s", log_file)

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                event = None if lightweight_events else self.parser.parse_line(line)
                if event:
                    result.events.append(event)
                    self._update_counters_from_event(result, event)
                else:
                    self._try_parse_stats(line, result, lightweight_events)

    def _update_counters_from_event(self, result: SyncResult, event: SyncEvent) -> None:
        """Update result counters based on event action."""
        if event.action == "added":
            result.num_added += 1
            result.bytes_transferred += event.file_size
        elif event.action == "updated":
            result.num_updated += 1
            result.bytes_transferred += event.file_size
        elif event.action == "error":
            result.errors += 1
        elif event.action == "conflict":
            result.errors += 1
            logger.warning("File conflict detected: %s", event.file_path)

    def _try_parse_stats(
        self, line: str, result: SyncResult, lightweight_events: bool
    ) -> None:
        """Try to parse stats from a log line."""
        parsed_stats: Optional[Dict[str, int]] = None

        try:
            obj = json.loads(line)
            msg = obj.get("msg", "") if isinstance(obj, dict) else ""
            if msg:
                parsed_stats = self.parser.parse_stats_line(msg)
        except Exception:
            parsed_stats = self.parser.parse_stats_line(line)

        if parsed_stats:
            logger.debug("Parsed stats: %s", parsed_stats)
            result.num_added = parsed_stats.get("files", 0)
            result.bytes_transferred = parsed_stats.get("transferred", 0)
            result.errors = parsed_stats.get("errors", 0)

            if not lightweight_events and parsed_stats.get("files", 0) > 0:
                generic_event = SyncEvent(
                    timestamp=_utc_now(),
                    action="added",
                    file_path="<stats-based-sync>",
                    file_size=parsed_stats.get("transferred", 0),
                    message=f"Stats: {parsed_stats.get('files', 0)} files",
                    file_hash=None,
                )
                result.events.append(generic_event)

    def test_connection(self, remote: str) -> Tuple[bool, str]:
        """Test connection to a remote (synchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "lsd", f"{remote}:", f"--config={rclone_conf}", "--max-depth=1"]

            if self.rclone_config.get("fast_list"):
                cmd.append("--fast-list")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return True, "Connection successful"
            return False, result.stderr.strip()

        except subprocess.TimeoutExpired:
            return False, "Connection timeout"
        except Exception as e:
            return False, str(e)

    def list_files(self, remote: str, path: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """List files in a remote path (synchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            remote_path = f"{remote}:{path}" if path else f"{remote}:"

            cmd = [
                "rclone",
                "lsjson",
                remote_path,
                f"--config={rclone_conf}",
                "--max-depth=1",
                "--no-modtime",
                "--no-mimetype",
            ]

            if self.rclone_config.get("fast_list"):
                cmd.append("--fast-list")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                files = json.loads(result.stdout)
                return files[:limit]
            logger.error("Failed to list files: %s", result.stderr)
            return []

        except Exception as e:
            logger.error("Error listing files: %s", e)
            return []

    def list_folders(self, remote_name: str, path: str = "") -> List[str]:
        """List folders in a remote (synchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            remote_path = f"{remote_name}:{path}" if path else f"{remote_name}:"
            base_cmd = [
                "rclone",
                "lsd",
                remote_path,
                "--max-depth=1",
                f"--config={rclone_conf}",
            ]

            if self.rclone_config.get("fast_list"):
                base_cmd.append("--fast-list")

            logger.info("RcloneRunner: listing folders remote='%s' path='%s'", remote_name, path)

            result = subprocess.run(base_cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0 and self._remote_supports_shared_drives(remote_name):
                gworkspace_cmd = base_cmd + ["--drive-shared-with-me"]
                logger.warning(
                    "RcloneRunner: initial lsd failed, retrying with --drive-shared-with-me"
                )
                retry = subprocess.run(gworkspace_cmd, capture_output=True, text=True, timeout=30)
                if retry.returncode == 0:
                    result = retry

            if result.returncode != 0:
                logger.error("Failed to list folders: %s", result.stderr)
                return []

            return self._parse_folder_output(result.stdout, path)

        except Exception as e:
            logger.error("Failed to list folders: %s", e)
            return []

    def _parse_folder_output(self, stdout: str, path: str) -> List[str]:
        """Parse rclone lsd output to extract folder names."""
        folders = []
        for line in stdout.strip().split("\n"):
            if line.strip():
                parts = line.strip().split()
                if len(parts) >= 4:
                    folder_name = " ".join(parts[4:])
                    full_path = f"{path}/{folder_name}" if path else folder_name
                    folders.append(full_path)
        return sorted(folders)

    def test_webdav_connection(
        self, url: str, user: str, password: str, remote_name: str
    ) -> Dict[str, Any]:
        """Test WebDAV connection and create rclone remote (synchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()

            cmd = [
                "rclone",
                "config",
                "create",
                remote_name,
                "webdav",
                f"url={url}",
                "vendor=nextcloud",
                f"user={user}",
                f"pass={password}",
                f"--config={rclone_conf}",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                return {"success": False, "error": f"Failed to create remote: {result.stderr}"}

            test_cmd = [
                "rclone",
                "lsd",
                f"{remote_name}:",
                "--max-depth=1",
                f"--config={rclone_conf}",
            ]

            if self.rclone_config.get("fast_list"):
                test_cmd.append("--fast-list")

            test_result = subprocess.run(test_cmd, capture_output=True, text=True, timeout=30)

            if test_result.returncode == 0:
                return {"success": True, "message": "WebDAV remote created and tested successfully"}

            self._remove_remote_sync(remote_name)
            return {"success": False, "error": f"Connection test failed: {test_result.stderr}"}

        except Exception as e:
            logger.error("WebDAV test failed: %s", e)
            return {"success": False, "error": str(e)}

    def estimate_sync_size(self, source: str, dest: str) -> Dict[str, Any]:
        """Estimate the size of a sync operation (synchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "size", source, "--json", f"--config={rclone_conf}"]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                logger.warning("Size estimation failed: %s", result.stderr)
                return {"size_mb": 0, "file_count": 0, "folder_count": 0}

            size_data = json.loads(result.stdout)
            size_bytes = size_data.get("bytes", 0)
            file_count = size_data.get("count", 0)

            return {
                "size_mb": round(size_bytes / 1024 / 1024, 2),
                "file_count": file_count,
                "folder_count": 0,
            }

        except Exception as e:
            logger.error("Size estimation failed: %s", e)
            return {"size_mb": 0, "file_count": 0, "folder_count": 0}

    def _remove_remote_sync(self, remote_name: str) -> bool:
        """Remove an rclone remote configuration (synchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "config", "delete", remote_name, f"--config={rclone_conf}"]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0

        except Exception as e:
            logger.error("Failed to remove remote %s: %s", remote_name, e)
            return False

    def remove_remote(self, remote_name: str) -> bool:
        """Public wrapper to remove rclone remote configurations (synchronous)."""
        removed = self._remove_remote_sync(remote_name)
        if removed:
            logger.info("rclone remote '%s' removed", remote_name)
        else:
            logger.warning("Unable to remove rclone remote '%s'", remote_name)
        return removed

    def _remote_supports_shared_drives(self, remote_name: str) -> bool:
        """Check whether the remote is a Google Drive remote."""
        remote_type = self._get_remote_type_sync(remote_name)
        return remote_type == "drive"

    def _get_remote_type_sync(self, remote_name: str) -> Optional[str]:
        """Inspect rclone config to determine the remote type (synchronous)."""
        key = remote_name.rstrip(":")
        if key in self._remote_type_cache:
            return self._remote_type_cache[key]

        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "config", "dump", f"--config={rclone_conf}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                logger.warning("Unable to inspect remote '%s' type: %s", key, result.stderr)
                self._remote_type_cache[key] = None
                return None

            config_dump = json.loads(result.stdout)
            remote_settings = config_dump.get(key)
            remote_type = remote_settings.get("type") if isinstance(remote_settings, dict) else None
            self._remote_type_cache[key] = remote_type
            logger.info("RcloneRunner: remote '%s' detected as type '%s'", key, remote_type)
            return remote_type

        except Exception as e:
            logger.error("Failed to determine remote '%s' type: %s", key, e)
            self._remote_type_cache[key] = None
            return None

    # =========================================================================
    # ASYNCHRONOUS METHODS (for FastAPI endpoints)
    # =========================================================================

    async def test_connection_async(self, remote: str) -> Tuple[bool, str]:
        """Test connection to a remote (asynchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "lsd", f"{remote}:", f"--config={rclone_conf}", "--max-depth=1"]

            if self.rclone_config.get("fast_list"):
                cmd.append("--fast-list")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return False, "Connection timeout"

            if process.returncode == 0:
                return True, "Connection successful"
            return False, stderr.decode().strip()

        except Exception as e:
            return False, str(e)

    async def list_files_async(
        self, remote: str, path: str = "", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List files in a remote path (asynchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            remote_path = f"{remote}:{path}" if path else f"{remote}:"

            cmd = [
                "rclone",
                "lsjson",
                remote_path,
                f"--config={rclone_conf}",
                "--max-depth=1",
                "--no-modtime",
                "--no-mimetype",
            ]

            if self.rclone_config.get("fast_list"):
                cmd.append("--fast-list")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return []

            if process.returncode == 0:
                files = json.loads(stdout.decode())
                return files[:limit]

            logger.error("Failed to list files: %s", stderr.decode())
            return []

        except Exception as e:
            logger.error("Error listing files: %s", e)
            return []

    async def list_folders_async(self, remote_name: str, path: str = "") -> List[str]:
        """List folders in a remote (asynchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            remote_path = f"{remote_name}:{path}" if path else f"{remote_name}:"
            base_cmd = [
                "rclone",
                "lsd",
                remote_path,
                "--max-depth=1",
                f"--config={rclone_conf}",
            ]

            if self.rclone_config.get("fast_list"):
                base_cmd.append("--fast-list")

            logger.info("RcloneRunner: listing folders async remote='%s' path='%s'", remote_name, path)

            process = await asyncio.create_subprocess_exec(
                *base_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return []

            if process.returncode != 0 and await self._remote_supports_shared_drives_async(remote_name):
                gworkspace_cmd = base_cmd + ["--drive-shared-with-me"]
                logger.warning("RcloneRunner: retrying with --drive-shared-with-me")

                retry_process = await asyncio.create_subprocess_exec(
                    *gworkspace_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(retry_process.communicate(), timeout=30)
                except asyncio.TimeoutError:
                    retry_process.kill()
                    await retry_process.wait()
                    return []

                if retry_process.returncode != 0:
                    logger.error("Failed to list folders: %s", stderr.decode())
                    return []
            elif process.returncode != 0:
                logger.error("Failed to list folders: %s", stderr.decode())
                return []

            return self._parse_folder_output(stdout.decode(), path)

        except Exception as e:
            logger.error("Failed to list folders: %s", e)
            return []

    async def test_webdav_connection_async(
        self, url: str, user: str, password: str, remote_name: str
    ) -> Dict[str, Any]:
        """Test WebDAV connection and create rclone remote (asynchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()

            cmd = [
                "rclone",
                "config",
                "create",
                remote_name,
                "webdav",
                f"url={url}",
                "vendor=nextcloud",
                f"user={user}",
                f"pass={password}",
                f"--config={rclone_conf}",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {"success": False, "error": "Timeout creating remote"}

            if process.returncode != 0:
                return {"success": False, "error": f"Failed to create remote: {stderr.decode()}"}

            # Test the connection
            test_cmd = [
                "rclone",
                "lsd",
                f"{remote_name}:",
                "--max-depth=1",
                f"--config={rclone_conf}",
            ]

            if self.rclone_config.get("fast_list"):
                test_cmd.append("--fast-list")

            test_process = await asyncio.create_subprocess_exec(
                *test_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                test_stdout, test_stderr = await asyncio.wait_for(
                    test_process.communicate(), timeout=30
                )
            except asyncio.TimeoutError:
                test_process.kill()
                await test_process.wait()
                await self._remove_remote_async(remote_name)
                return {"success": False, "error": "Timeout testing connection"}

            if test_process.returncode == 0:
                return {"success": True, "message": "WebDAV remote created and tested successfully"}

            await self._remove_remote_async(remote_name)
            return {"success": False, "error": f"Connection test failed: {test_stderr.decode()}"}

        except Exception as e:
            logger.error("WebDAV test failed: %s", e)
            return {"success": False, "error": str(e)}

    async def estimate_sync_size_async(self, source: str, dest: str) -> Dict[str, Any]:
        """Estimate the size of a sync operation (asynchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "size", source, "--json", f"--config={rclone_conf}"]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {"size_mb": 0, "file_count": 0, "folder_count": 0}

            if process.returncode != 0:
                logger.warning("Size estimation failed: %s", stderr.decode())
                return {"size_mb": 0, "file_count": 0, "folder_count": 0}

            size_data = json.loads(stdout.decode())
            size_bytes = size_data.get("bytes", 0)
            file_count = size_data.get("count", 0)

            return {
                "size_mb": round(size_bytes / 1024 / 1024, 2),
                "file_count": file_count,
                "folder_count": 0,
            }

        except Exception as e:
            logger.error("Size estimation failed: %s", e)
            return {"size_mb": 0, "file_count": 0, "folder_count": 0}

    async def _remove_remote_async(self, remote_name: str) -> bool:
        """Remove an rclone remote configuration (asynchronous)."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "config", "delete", remote_name, f"--config={rclone_conf}"]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                await asyncio.wait_for(process.communicate(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return False

            return process.returncode == 0

        except Exception as e:
            logger.error("Failed to remove remote %s: %s", remote_name, e)
            return False

    async def remove_remote_async(self, remote_name: str) -> bool:
        """Public wrapper to remove rclone remote configurations (asynchronous)."""
        removed = await self._remove_remote_async(remote_name)
        if removed:
            logger.info("rclone remote '%s' removed", remote_name)
        else:
            logger.warning("Unable to remove rclone remote '%s'", remote_name)
        return removed

    async def _remote_supports_shared_drives_async(self, remote_name: str) -> bool:
        """Check whether the remote is a Google Drive remote (asynchronous)."""
        remote_type = await self._get_remote_type_async(remote_name)
        return remote_type == "drive"

    async def _get_remote_type_async(self, remote_name: str) -> Optional[str]:
        """Inspect rclone config to determine the remote type (asynchronous)."""
        key = remote_name.rstrip(":")
        if key in self._remote_type_cache:
            return self._remote_type_cache[key]

        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "config", "dump", f"--config={rclone_conf}"]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                self._remote_type_cache[key] = None
                return None

            if process.returncode != 0:
                logger.warning("Unable to inspect remote '%s' type: %s", key, stderr.decode())
                self._remote_type_cache[key] = None
                return None

            config_dump = json.loads(stdout.decode())
            remote_settings = config_dump.get(key)
            remote_type = remote_settings.get("type") if isinstance(remote_settings, dict) else None
            self._remote_type_cache[key] = remote_type
            logger.info("RcloneRunner: remote '%s' detected as type '%s'", key, remote_type)
            return remote_type

        except Exception as e:
            logger.error("Failed to determine remote '%s' type: %s", key, e)
            self._remote_type_cache[key] = None
            return None


# Global runner instance
_runner: Optional[RcloneRunner] = None


def get_runner() -> RcloneRunner:
    """Get the global rclone runner instance."""
    global _runner
    if _runner is None:
        _runner = RcloneRunner()
    return _runner
