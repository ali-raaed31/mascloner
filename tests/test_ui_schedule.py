"""Unit tests for Schedule and Engine tuning presets."""

import pytest
from app.ui.pages.schedule import PRESETS


def test_rclone_engine_presets():
    balanced = PRESETS["Balanced (Recommended)"]
    assert balanced["transfers"] == 8
    assert balanced["checkers"] == 16
    assert balanced["tpslimit"] == 25
    assert balanced["use_fast_list"] is True

    conservative = PRESETS["Conservative (Low Resource)"]
    assert conservative["transfers"] == 4
    assert conservative["checkers"] == 8

    high_thru = PRESETS["High-Throughput (Fast Network)"]
    assert high_thru["transfers"] == 16
    assert high_thru["checkers"] == 32
