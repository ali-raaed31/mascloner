"""Live Sync Monitor with isolated non-blocking telemetry streaming."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_bytes,
        format_duration,
        format_iso_time,
        get_status_badge_meta,
        render_hero_bar,
        render_status_pill,
    )
except ImportError:
    from api_client import APIClient
    from components.theme import (
        format_bytes,
        format_duration,
        format_iso_time,
        get_status_badge_meta,
        render_hero_bar,
        render_status_pill,
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
    log_filter = st.selectbox(
        "Log Level Filter",
        options=["All Logs", "Errors & Warnings Only", "Errors Only"],
        index=0,
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
    current_run = api.get_current_run()

    if current_run:
        run_id = current_run.get("id")
        st.session_state.monitored_run_id = run_id

        pct = float(current_run.get("percentage") or 0.0)
        progress_val = min(max(pct / 100.0, 0.0), 1.0)
        st.progress(progress_val, text=f"Syncing Run #{run_id} — {pct:.1f}%")

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            trans = current_run.get("bytes_transferred", 0)
            total = current_run.get("total_bytes", 0)
            st.metric("Transferred", f"{format_bytes(trans)}", f"of {format_bytes(total)}" if total else None)
        with m2:
            speed = current_run.get("speed_bps", 0)
            st.metric("Current Speed", f"{format_bytes(speed)}/s")
        with m3:
            f_trans = current_run.get("files_transferred", 0)
            f_total = current_run.get("total_files", 0)
            st.metric("Files Progress", f"{f_trans}", f"of {f_total}" if f_total else None)
        with m4:
            elapsed = current_run.get("elapsed_seconds")
            st.metric("Elapsed Time", format_duration(elapsed))

        curr_file = current_run.get("current_file")
        if curr_file:
            st.markdown(f"📄 **Active File**: `{curr_file}`")

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
        recent_runs_resp = api.get_runs(limit=1) or {}
        recent = recent_runs_resp.get("runs", [])
        last_run = recent[0] if recent else None

        if last_run:
            run_id = last_run.get("id")
            status = last_run.get("status", "unknown")
            meta = get_status_badge_meta(status)

            if status == "completed":
                st.success(f"### {meta['icon']} Run #{run_id} Completed Successfully")
            elif status == "failed":
                st.error(f"### {meta['icon']} Run #{run_id} Failed: {last_run.get('error_message') or 'Unknown error'}")
            else:
                st.info(f"### {meta['icon']} Run #{run_id} Status: {meta['label']}")

            fin_col1, fin_col2, fin_col3 = st.columns(3)
            with fin_col1:
                st.metric("Total Transferred", format_bytes(last_run.get("bytes_transferred")))
            with fin_col2:
                st.metric("Files Mutated", f"{last_run.get('files_transferred', 0)} files")
            with fin_col3:
                st.metric("Duration", format_duration(last_run.get("duration")))

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
        st.code(log_content, language="bash")
    else:
        st.caption("No log entries match the selected filter.")


# Execute the fragment
render_live_telemetry()
