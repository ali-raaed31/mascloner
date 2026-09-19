"""Unit tests for Schedule and Engine tuning presets."""

import pytest
from app.ui.api_client import RclonePerformanceContract
from app.ui.pages.schedule import PRESETS, apply_engine_preset


def test_rclone_engine_presets():
    balanced = PRESETS["Balanced (Recommended)"]
    assert balanced["transfers"] == 8
    assert balanced["checkers"] == 16
    assert balanced["tpslimit"] == 25
    assert balanced["tpslimit_burst"] == 1
    assert balanced["fast_list"] is True

    conservative = PRESETS["Conservative (Low Resource)"]
    assert conservative["transfers"] == 4
    assert conservative["checkers"] == 8

    high_thru = PRESETS["High-Throughput (Fast Network)"]
    assert high_thru["transfers"] == 16
    assert high_thru["checkers"] == 32


def test_engine_preset_preserves_optional_persisted_settings():
    current = RclonePerformanceContract(
        transfers=4,
        checkers=8,
        tpslimit=10,
        tpslimit_burst=1,
        buffer_size="16Mi",
        drive_chunk_size="32M",
        drive_upload_cutoff="256M",
        fast_list=False,
    )
    updated = apply_engine_preset(current, PRESETS["Balanced (Recommended)"])
    assert updated.drive_upload_cutoff == "256M"
    assert updated.drive_chunk_size == "32M"
    assert updated.buffer_size == "16Mi"
    assert updated.tpslimit_burst == 1
