"""Theme, formatters, and status rendering components for MasCloner UI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union
import streamlit as st


def format_bytes(bytes_val: Optional[Union[int, float]]) -> str:
    """Format a byte count into a human-readable string (B, KB, MB, GB, TB)."""
    if bytes_val is None or bytes_val <= 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(bytes_val)
    unit_index = 0

    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} B"
    return f"{value:.2f} {units[unit_index]}"


def format_duration(seconds: Optional[Union[int, float]]) -> str:
    """Format duration in seconds into human-readable format (<1s, 45s, 1m 20s, 2h 10m)."""
    if seconds is None:
        return "-"
    if seconds == 0:
        return "0s"
    if seconds < 1.0:
        return "<1s"

    secs = int(round(seconds))
    hours, remainder = divmod(secs, 3600)
    minutes, rem_secs = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m {rem_secs:02d}s"
    return f"{rem_secs}s"


def format_iso_time(iso_str: Optional[str], include_relative: bool = True) -> str:
    """Format an ISO 8601 timestamp string into human readable and relative time."""
    if not iso_str:
        return "-"

    try:
        # Normalize trailing Z
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        formatted_utc = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if not include_relative:
            return formatted_utc

        now = datetime.now(timezone.utc)
        diff = now - dt
        diff_secs = int(diff.total_seconds())

        if diff_secs < 0:
            rel = "in the future"
        elif diff_secs < 5:
            rel = "just now"
        elif diff_secs < 60:
            rel = f"{diff_secs}s ago"
        elif diff_secs < 3600:
            rel = f"{diff_secs // 60}m ago"
        elif diff_secs < 86400:
            rel = f"{diff_secs // 3600}h ago"
        else:
            rel = f"{diff_secs // 86400}d ago"

        return f"{formatted_utc} ({rel})"
    except Exception:
        return iso_str


STATUS_META = {
    "completed": {"label": "Completed", "color": "green", "icon": "🟢"},
    "running": {"label": "Running", "color": "blue", "icon": "🔵"},
    "failed": {"label": "Failed", "color": "red", "icon": "🔴"},
    "aborted": {"label": "Aborted", "color": "orange", "icon": "🟠"},
    "skipped": {"label": "Skipped", "color": "gray", "icon": "⚪"},
    "pending": {"label": "Pending", "color": "yellow", "icon": "🟡"},
}


def get_status_badge_meta(status_str: Optional[str]) -> Dict[str, str]:
    """Get status metadata (label, color, icon) for a given canonical SyncStatus."""
    key = (status_str or "").strip().lower()
    return STATUS_META.get(
        key, {"label": (status_str or "Unknown").capitalize(), "color": "gray", "icon": "⚪"}
    )


def render_status_pill(status_str: Optional[str]) -> str:
    """Return markdown string with icon and status label."""
    meta = get_status_badge_meta(status_str)
    return f"{meta['icon']} **{meta['label']}**"


def render_hero_bar(api_client) -> None:
    """Render the top hero operational bar across dashboard and views."""
    status_data = api_client.get_status() or {}
    schedule_data = api_client.get_schedule() or {}
    current_run = api_client.get_current_run()

    is_running = bool(current_run)
    run_id = current_run.get("id") if current_run else None
    sched_enabled = schedule_data.get("enabled", False)
    interval_minutes = schedule_data.get("interval_minutes", 15)

    col1, col2, col3, col4 = st.columns([1.2, 1.2, 1.2, 1.4])

    with col1:
        if is_running:
            st.markdown(f"### 🔵 Sync #{run_id}")
            st.caption("Active & Syncing")
        else:
            st.markdown("### 🟢 Engine Idle")
            st.caption("Awaiting Next Run")

    with col2:
        if sched_enabled:
            st.markdown(f"### ⏱️ Active ({interval_minutes}m)")
            st.caption("Schedule Enabled")
        else:
            st.markdown("### ⏸️ Paused")
            st.caption("Schedule Disabled")

    with col3:
        next_run_iso = schedule_data.get("next_run_time")
        if next_run_iso and sched_enabled:
            st.markdown(f"### ⏳ Next Run")
            st.caption(format_iso_time(next_run_iso, include_relative=True))
        else:
            st.markdown("### ⏳ Next Run")
            st.caption("None Scheduled" if not sched_enabled else "Calculating...")

    with col4:
        db_info = api_client.get_database_info() or {}
        total_runs = db_info.get("total_runs", 0)
        st.markdown(f"### 📊 Total: {total_runs}")
        st.caption("Sync Runs Recorded")

    st.divider()


def generate_run_csv(events: list[dict[str, Any]]) -> str:
    """Generate CSV string from file events list."""
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "Action", "File Path", "Size (Bytes)", "Message"])
    for ev in events:
        writer.writerow([
            ev.get("id", ""),
            ev.get("timestamp", ""),
            ev.get("action", ""),
            ev.get("file_path", ""),
            ev.get("file_size", 0),
            ev.get("message", "") or "",
        ])
    return output.getvalue()
