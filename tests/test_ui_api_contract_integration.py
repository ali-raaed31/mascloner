"""Exercise the UI contract adapters against actual FastAPI response shapes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.api.db import get_db_session
from app.api.models import Run, SyncStatus
from app.ui.api_client import APIClient, ScheduleUpdateContract


def test_ui_contracts_round_trip_with_fastapi(fresh_client: TestClient, monkeypatch) -> None:
    ui = APIClient(base_url="http://127.0.0.1:8787")

    def api_backed_request(method: str, endpoint: str, **kwargs):
        response = fresh_client.request(method, endpoint, **kwargs)
        if response.status_code >= 400:
            detail = response.json().get("detail", response.text)
            return {"success": False, "message": str(detail)}
        return response.json()

    monkeypatch.setattr(ui, "_make_request", api_backed_request)

    saved = ui.save_schedule(
        ScheduleUpdateContract(enabled=True, interval_min=120, jitter_sec=20)
    )
    assert saved.success is True
    schedule = ui.get_schedule_settings()
    assert schedule is not None
    assert (schedule.interval_min, schedule.jitter_sec, schedule.enabled) == (120, 20, True)

    invalid = ui.save_schedule(
        ScheduleUpdateContract(enabled=True, interval_min=1, jitter_sec=300)
    )
    assert invalid.success is False
    assert "jitter" in invalid.message.lower()
    assert ui.get_schedule_settings().interval_min == 120

    assert ui.set_schedule_paused(True).success is True
    assert ui.get_schedule_settings().enabled is False
    assert ui.set_schedule_paused(False).success is True
    assert ui.get_schedule_settings().enabled is True

    performance = ui.get_rclone_performance()
    assert performance is not None
    changed = performance.model_copy(update={"transfers": 6, "tpslimit_burst": 3, "fast_list": True})
    assert ui.save_rclone_performance(changed).success is True
    reloaded = ui.get_rclone_performance()
    assert reloaded is not None
    assert (reloaded.transfers, reloaded.tpslimit_burst, reloaded.fast_list) == (6, 3, True)
    assert reloaded.drive_upload_cutoff == performance.drive_upload_cutoff

    started = datetime.now(timezone.utc) - timedelta(seconds=90)
    with get_db_session() as db:
        db.add(
            Run(
                status=SyncStatus.COMPLETED,
                started_at=started,
                finished_at=started + timedelta(seconds=90),
                num_added=2,
                num_updated=1,
                bytes_transferred=1024,
                errors=0,
            )
        )
        db.commit()
    runs = ui.get_recent_runs(limit=1)
    assert runs is not None and len(runs) == 1
    assert runs[0].mutation_count == 3
    assert runs[0].duration_seconds == 90

    assert ui.get_google_drive_endpoint_status() is not None
    assert ui.get_nextcloud_endpoint_status() is not None
