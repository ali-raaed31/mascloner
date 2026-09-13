"""Unit tests for History view CSV generation and event formatting."""

import pytest
from app.ui.components.theme import generate_run_csv


def test_generate_run_csv():
    events = [
        {
            "id": 1,
            "timestamp": "2026-09-13T23:55:00Z",
            "action": "added",
            "file_path": "Accounting/2026_ledger.xlsx",
            "file_size": 1048576,
            "message": "Copied successfully",
        },
        {
            "id": 2,
            "timestamp": "2026-09-13T23:55:02Z",
            "action": "error",
            "file_path": "Accounting/locked.pdf",
            "file_size": 2048,
            "message": "Permission denied (403)",
        },
    ]

    csv_out = generate_run_csv(events)
    lines = csv_out.strip().split("\r\n" if "\r\n" in csv_out else "\n")

    assert len(lines) == 3
    assert "ID,Timestamp,Action,File Path,Size (Bytes),Message" in lines[0]
    assert "Accounting/2026_ledger.xlsx" in lines[1]
    assert "added" in lines[1]
    assert "Accounting/locked.pdf" in lines[2]
    assert "Permission denied (403)" in lines[2]
