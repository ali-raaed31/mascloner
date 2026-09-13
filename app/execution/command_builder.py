"""Rclone command builder for SyncExecutor (ADR 0004, ADR 0005)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..configuration.models import RclonePerformanceSettings, SyncPathsSettings


class RcloneCommandBuilder:
    """Builds rclone commands strictly from fixed endpoints and validated snapshots."""

    SOURCE_REMOTE = "gdrive"
    DEST_REMOTE = "ncwebdav"

    @classmethod
    def build_sync_command(
        cls,
        paths: SyncPathsSettings,
        perf: RclonePerformanceSettings,
        rclone_conf_path: Path,
        log_file_path: Path,
        rclone_bin: str = "rclone",
        dry_run: bool = False,
    ) -> List[str]:
        """Construct the immutable rclone command argument list."""
        src_path = paths.gdrive_src.strip().lstrip("/")
        dest_path = paths.nc_dest_path.strip().lstrip("/")

        src_target = f"{cls.SOURCE_REMOTE}:{src_path}"
        dest_target = f"{cls.DEST_REMOTE}:{dest_path}"

        cmd = [
            rclone_bin,
            "copy",
            src_target,
            dest_target,
            f"--config={rclone_conf_path}",
            f"--log-file={log_file_path}",
            "--use-json-log",
            "--log-level=INFO",
            "--stats-log-level=NOTICE",
            "--stats=1s",
            "--stats-one-line",
            f"--checkers={perf.checkers}",
            f"--transfers={perf.transfers}",
            f"--tpslimit={perf.tpslimit}",
            "--drive-shared-with-me",
            "--drive-skip-shortcuts",
            "--drive-export-formats=docx,xlsx,pptx",
        ]

        if perf.buffer_size:
            cmd.append(f"--buffer-size={perf.buffer_size}")
        if perf.tpslimit_burst:
            cmd.append(f"--tpslimit-burst={perf.tpslimit_burst}")
        if perf.fast_list:
            cmd.append("--fast-list")
        if perf.drive_chunk_size:
            cmd.append(f"--drive-chunk-size={perf.drive_chunk_size}")
        if perf.drive_upload_cutoff:
            cmd.append(f"--drive-upload-cutoff={perf.drive_upload_cutoff}")
        if dry_run:
            cmd.append("--dry-run")

        return cmd
