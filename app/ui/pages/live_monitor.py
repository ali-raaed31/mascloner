"""Live Sync Monitor with isolated non-blocking telemetry streaming."""

from __future__ import annotations

import json
from typing import Any
import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_bytes,
        format_duration,
        get_status_badge_meta,
        render_hero_bar,
    )
except ImportError:
    from api_client import APIClient
    from components.theme import (
        format_bytes,
        format_duration,
        get_status_badge_meta,
        render_hero_bar,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()

st.title("📡 Live Monitor")
render_hero_bar(api)

# Session state initialization for log tracking
if "live_logs" not in st.session_state:
    st.session_state.live_logs = []
if "last_line" not in st.session_state:
    st.session_state.last_line = 0
if "monitored_run_id" not in st.session_state:
    st.session_state.monitored_run_id = None
if "stream_paused" not in st.session_state:
    st.session_state.stream_paused = False


# Controls bar (outside fragment so clicks are persistent)
filter_col1, filter_col2, filter_col3 = st.columns([1.5, 1.5, 1])
with filter_col1:
    log_filter = st.segmented_control(
        "Log Level Filter",
        options=["All Logs", "Errors & Warnings Only", "Errors Only"],
        default="All Logs",
    )
with filter_col2:
    auto_refresh = st.toggle("⚡ Live Polling Stream", value=True, help="Toggle automatic real-time streaming")
with filter_col3:
    if st.button("🧹 Clear Logs", use_container_width=True):
        st.session_state.live_logs = []
        st.session_state.last_line = 0
        st.rerun()

st.divider()


def format_log_entry(entry: Any) -> tuple[str, str]:
    """Parse log entry and return (level, formatted_string)."""
    if isinstance(entry, dict):
        raw_parsed = entry.get("parsed")
        if isinstance(raw_parsed, dict):
            level = str(raw_parsed.get("level", "info")).lower()
            msg = raw_parsed.get("msg") or raw_parsed.get("message") or ""
            obj = raw_parsed.get("object") or ""
            ts = raw_parsed.get("time") or entry.get("timestamp") or ""
            text = f"[{ts[:19]}] [{level.upper()}] {msg} {f'({obj})' if obj else ''}".strip()
            return level, text
        
        level = str(entry.get("level", "info")).lower()
        msg = entry.get("message") or entry.get("raw") or str(entry)
        return level, f"[{level.upper()}] {msg}"
    
    line = str(entry).strip()
    try:
        data = json.loads(line)
        level = str(data.get("level", "info")).lower()
        msg = data.get("msg") or data.get("message") or line
        return level, f"[{level.upper()}] {msg}"
    except Exception:
        lower = line.lower()
        if "error" in lower:
            return "error", line
        if "warn" in lower:
            return "warning", line
        return "info", line


@st.fragment(run_every="2s" if auto_refresh else None)
def render_live_telemetry():
    current_run = api.get_current_run_snapshot()

    if current_run:
        run_id = current_run.id
        st.session_state.monitored_run_id = run_id

        if current_run.percentage is None:
            st.info(f"Syncing Run #{run_id} — progress is unavailable from rclone.")
        else:
            pct = current_run.percentage
            progress_val = min(max(pct / 100.0, 0.0), 1.0)
            st.progress(progress_val, text=f"Syncing Run #{run_id} — {pct:.1f}%")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Transferred", format_bytes(current_run.bytes_transferred), "Total unavailable")
        with m2:
            speed = current_run.speed_bps
            st.metric("Current Speed", f"{format_bytes(speed)}/s" if speed is not None else "Unavailable")
        with m3:
            st.metric("Files Mutated", f"{current_run.mutation_count}", "Total unavailable")
        with m4:
            st.metric("Elapsed Time", format_duration(current_run.elapsed_seconds))

        # Stop button
        if st.button("🛑 Stop Active Sync", type="secondary", key="live_stop_btn"):
            api.stop_run(run_id)
            st.warning(f"Stop signal dispatched to Run #{run_id}.")

        # Fetch incremental logs
        logs_resp = api.get_run_logs(
            run_id,
            since=st.session_state.last_line,
            limit=100,
        )
        if logs_resp:
            new_logs = logs_resp.get("logs") or []
            if new_logs:
                st.session_state.live_logs.extend(new_logs)
                st.session_state.last_line = logs_resp.get("next_line", st.session_state.last_line + len(new_logs))

    else:
        # No sync is actively running
        recent = api.get_recent_runs(limit=1) or []
        last_run = recent[0] if recent else None

        if last_run:
            run_id = last_run.id
            status = last_run.status
            meta = get_status_badge_meta(status)

            if status == "completed":
                st.success(f"### {meta['icon']} Run #{run_id} Completed Successfully")
            elif status == "failed":
                st.error(f"### {meta['icon']} Run #{run_id} Failed: {last_run.message or 'Unknown error'}")
            else:
                st.info(f"### {meta['icon']} Run #{run_id} Status: {meta['label']}")

            fin_col1, fin_col2, fin_col3 = st.columns(3)
            with fin_col1:
                st.metric("Total Transferred", format_bytes(last_run.bytes_transferred))
            with fin_col2:
                st.metric("Files Mutated", f"{last_run.mutation_count} files")
            with fin_col3:
                st.metric("Duration", format_duration(last_run.duration_seconds))

            if last_run.errors:
                st.error(f"Errors recorded: {last_run.errors}")

            # Navigation buttons (Q10=A)
            nav_col1, nav_col2 = st.columns(2)
            with nav_col1:
                if st.button("📊 Return to Live Dashboard", use_container_width=True, key="back_to_dash"):
                    st.switch_page("pages/dashboard.py")
            with nav_col2:
                if st.button("📋 View Full Audit in History", use_container_width=True, key="view_hist"):
                    st.switch_page("pages/history.py")

            # Load past logs if empty
            if not st.session_state.live_logs:
                logs_resp = api.get_run_logs(run_id, since=0, limit=100) or {}
                st.session_state.live_logs = logs_resp.get("logs") or []
        else:
            st.info("Engine is currently idle. No sync has been recorded yet.")
            if st.button("📊 Go to Dashboard to Start Sync", key="idle_to_dash"):
                st.switch_page("pages/dashboard.py")

    # Render Terminal Log Stream
    st.markdown("### 💻 Real-Time Console Stream")
    
    # Filter logs according to operator selection
    rendered_lines = []
    for log_item in st.session_state.live_logs:
        level, line_text = format_log_entry(log_item)
        if log_filter == "Errors Only" and level != "error":
            continue
        if log_filter == "Errors & Warnings Only" and level not in ("error", "warning"):
            continue
        rendered_lines.append(line_text)

    if rendered_lines:
        log_content = "\n".join(rendered_lines[-200:])  # display latest 200 lines
        st.code(log_content, language="bash", height=420)
    else:
        st.caption("No log entries match the selected filter.")


# Execute the fragment
render_live_telemetry()
