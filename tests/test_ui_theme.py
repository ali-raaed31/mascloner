"""Unit tests for UI theme, formatters, and status rendering."""

from datetime import datetime, timezone, timedelta
import pytest

from app.ui.components.theme import (
    format_bytes,
    format_duration,
    format_iso_time,
    get_status_badge_meta,
)


def test_format_bytes():
    assert format_bytes(None) == "0 B"
    assert format_bytes(0) == "0 B"
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1536) == "1.50 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2.5) == "2.50 GB"


def test_format_duration():
    assert format_duration(None) == "-"
    assert format_duration(0) == "0s"
    assert format_duration(0.4) == "<1s"
    assert format_duration(45) == "45s"
    assert format_duration(65) == "1m 05s"
    assert format_duration(3665) == "1h 01m"


def test_format_iso_time():
    assert format_iso_time(None) == "-"
    assert format_iso_time("") == "-"
    
    # Valid ISO string
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.isoformat()
    formatted = format_iso_time(now_iso, include_relative=True)
    assert "UTC" in formatted
    assert "ago" in formatted or "just now" in formatted


def test_get_status_badge_meta():
    completed = get_status_badge_meta("completed")
    assert completed["label"] == "Completed"
    assert completed["color"] == "green"

    running = get_status_badge_meta("running")
    assert running["label"] == "Running"
    assert running["color"] == "blue"

    failed = get_status_badge_meta("failed")
    assert failed["label"] == "Failed"
    assert failed["color"] == "red"

    aborted = get_status_badge_meta("aborted")
    assert aborted["label"] == "Aborted"
    assert aborted["color"] == "orange"

    skipped = get_status_badge_meta("skipped")
    assert skipped["label"] == "Skipped"
    assert skipped["color"] == "gray"

    pending = get_status_badge_meta("pending")
    assert pending["label"] == "Pending"
    assert pending["color"] == "yellow"
