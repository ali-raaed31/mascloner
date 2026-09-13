"""Unit tests for Live Monitor log parsing and formatting."""

import pytest
from app.ui.pages.live_monitor import format_log_entry


def test_format_log_entry_json_dict():
    entry = {
        "parsed": {
            "level": "error",
            "msg": "Failed to transfer file.txt: 403 Forbidden",
            "object": "Finance/file.txt",
            "time": "2026-09-13T23:50:00Z",
        }
    }
    level, text = format_log_entry(entry)
    assert level == "error"
    assert "ERROR" in text
    assert "403 Forbidden" in text
    assert "Finance/file.txt" in text


def test_format_log_entry_raw_dict():
    entry = {"level": "warning", "message": "Rate limit approached, sleeping 2s"}
    level, text = format_log_entry(entry)
    assert level == "warning"
    assert "WARNING" in text
    assert "Rate limit approached" in text


def test_format_log_entry_plain_text():
    line = "2026/09/13 23:50:01 ERROR : document.pdf: Failed to copy"
    level, text = format_log_entry(line)
    assert level == "error"
    assert "Failed to copy" in text
