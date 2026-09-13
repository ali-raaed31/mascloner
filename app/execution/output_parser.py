"""Rclone JSON log parser for SyncExecutor (ADR 0005)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional, Tuple

from .models import FileEventEntry

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RcloneOutputParser:
    """Parser for rclone --use-json-log line events and statistics."""

    ACTION_MAP = {
        "Copied (new)": "copy",
        "Copied (replaced)": "replace",
        "Deleted": "delete",
        "Failed to copy": "error",
        "ERROR": "error",
        "Updated": "update",
    }

    @classmethod
    def parse_line(cls, line: str) -> Tuple[Optional[FileEventEntry], Optional[Dict[str, Any]]]:
        """Parse a single rclone JSON line.

        Returns:
            Tuple of (FileEventEntry or None, stats_dict or None)
        """
        raw = line.strip()
        if not raw:
            return None, None

        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, AttributeError):
            return None, None

        if not isinstance(obj, dict):
            return None, None

        # Check for stats update
        stats_data = obj.get("stats")
        if stats_data and isinstance(stats_data, dict):
            return None, stats_data

        # Check for file operation event
        msg = obj.get("msg", "")
        file_path = obj.get("object", "")
        file_size = int(obj.get("size", 0) or 0)
        timestamp_str = obj.get("time", "")

        ts = _utc_now()
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        action: Optional[str] = None
        for prefix, act in cls.ACTION_MAP.items():
            if msg.startswith(prefix):
                action = act
                break

        if action and file_path:
            event = FileEventEntry(
                action=action,
                file_path=file_path,
                file_size=file_size,
                timestamp=ts,
                message=msg,
            )
            return event, None

        # If it's an error message without action match
        if obj.get("level") == "error" and (file_path or msg):
            event = FileEventEntry(
                action="error",
                file_path=file_path or "system",
                file_size=file_size,
                timestamp=ts,
                message=msg,
            )
            return event, None

        return None, None
