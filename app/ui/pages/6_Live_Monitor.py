"""
MasCloner Live Sync Monitor

Real-time monitoring of running sync operations with log streaming
and graceful stop functionality.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

# Page config - must be first Streamlit command
st.set_page_config(
    page_title="Live Monitor - MasCloner",
    page_icon="📊",
    layout="wide",
)

# Import API client
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import APIClient
from components.auth import require_auth


def format_bytes(b: int) -> str:
    """Format bytes to human-readable string."""
    if b is None:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def format_duration(start_time: str) -> str:
    """Format duration since start time."""
    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        now = datetime.now(start.tzinfo)
        delta = now - start
        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes}m {seconds}s"
        else:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
    except Exception:
        return "Unknown"


def get_log_level_color(level: str) -> str:
    """Get CSS color for log level."""
    level = level.lower()
    if level == "error":
        return "#ff4b4b"
    elif level == "warning":
        return "#ffa500"
    elif level == "notice":
        return "#00d4ff"
    else:
        return "#ffffff"


def render_log_entry(log: Dict[str, Any]) -> None:
    """Render a single log entry with appropriate styling."""
    level = log.get("level", "info").lower()
    message = log.get("message", "")
    obj = log.get("object", "")
    timestamp = log.get("timestamp", "")

    # Format timestamp
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            time_str = timestamp[:8] if len(timestamp) >= 8 else timestamp
    else:
        time_str = ""

    # Build display text
    if obj:
        display_text = f"[{time_str}] {message}: {obj}"
    else:
        display_text = f"[{time_str}] {message}" if time_str else message

    # Render with appropriate styling
    if level == "error":
        st.error(display_text)
    elif level == "warning":
        st.warning(display_text)
    else:
        st.text(display_text)


# Initialize API client
@st.cache_resource
def get_api_client():
    return APIClient()


api = get_api_client()

# Check authentication
if not require_auth(api):
    st.stop()

# Page header
st.title("📊 Live Sync Monitor")
st.markdown("Monitor running sync operations in real-time")

# Check API connection
status = api.get_status()
if not status:
    st.error("Cannot connect to MasCloner API")
    st.stop()

st.markdown("---")

# Initialize session state for log tracking
if "last_line" not in st.session_state:
    st.session_state.last_line = 0
if "accumulated_logs" not in st.session_state:
    st.session_state.accumulated_logs = []
if "last_run_id" not in st.session_state:
    st.session_state.last_run_id = None

# Configuration
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    auto_refresh = st.checkbox("Auto-refresh (every 2 seconds)", value=True)

with col2:
    show_all_logs = st.checkbox("Show all log levels", value=True)

with col3:
    if st.button("Clear Logs", type="secondary"):
        st.session_state.accumulated_logs = []
        st.session_state.last_line = 0
        st.rerun()

st.markdown("---")

# Get current run
current_run = api.get_current_run()

if current_run is None:
    # No sync currently running
    st.info("No sync currently running")

    # Reset log state when no run
    if st.session_state.last_run_id is not None:
        st.session_state.last_run_id = None
        st.session_state.last_line = 0
        st.session_state.accumulated_logs = []

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Status", "Idle")

    with col2:
        scheduler_running = status.get("scheduler_running", False)
        st.metric("Scheduler", "Running" if scheduler_running else "Stopped")

    with col3:
        last_sync = status.get("last_sync", "Never")
        if last_sync and last_sync != "Never":
            try:
                dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                last_sync = dt.strftime("%m/%d %H:%M")
            except Exception:
                pass
        st.metric("Last Sync", last_sync)

    st.markdown("---")

    # Manual sync trigger
    st.subheader("Start a Sync")
    st.markdown("No sync is currently running. You can trigger one manually:")

    if st.button("Start Sync Now", type="primary", use_container_width=True):
        result = api.trigger_sync()
        if result and result.get("success"):
            st.success("Sync started! Refreshing...")
            time.sleep(1)
            st.rerun()
        else:
            st.error("Failed to start sync")

    # Show recent runs
    st.markdown("---")
    st.subheader("Recent Runs")

    runs = api.get_runs(limit=5)
    if runs:
        for run in runs:
            run_id = run.get("id", "?")
            run_status = run.get("status", "unknown")
            started = run.get("started_at", "")

            status_emoji = {
                "success": "✅",
                "error": "❌",
                "stopped": "🛑",
                "running": "🔄",
            }.get(run_status, "❓")

            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                time_str = dt.strftime("%m/%d %H:%M:%S")
            except Exception:
                time_str = started

            with st.expander(
                f"{status_emoji} Run #{run_id} - {time_str} ({run_status})"
            ):
                cols = st.columns(4)
                cols[0].metric("Added", run.get("num_added", 0))
                cols[1].metric("Updated", run.get("num_updated", 0))
                cols[2].metric("Transferred", format_bytes(run.get("bytes_transferred", 0)))
                cols[3].metric("Errors", run.get("errors", 0))
    else:
        st.info("No previous runs found")

else:
    # Sync is running
    run_id = current_run.get("id")
    run_status = current_run.get("status", "running")
    started_at = current_run.get("started_at", "")

    # Reset log state if this is a different run
    if st.session_state.last_run_id != run_id:
        st.session_state.last_run_id = run_id
        st.session_state.last_line = 0
        st.session_state.accumulated_logs = []

    # Status header
    col1, col2 = st.columns([3, 1])

    with col1:
        st.subheader(f"🔄 Sync Run #{run_id} in Progress")

    with col2:
        # Stop button
        if st.button("🛑 Stop Sync", type="primary", use_container_width=True):
            result = api.stop_run(run_id)
            if result and result.get("success"):
                st.warning("Stop requested - finishing current file...")
                time.sleep(2)
                st.rerun()
            else:
                error_msg = result.get("detail", "Failed to stop sync") if result else "Failed to stop sync"
                st.error(error_msg)

    # Progress metrics
    st.markdown("---")
    cols = st.columns(5)

    with cols[0]:
        st.metric("Status", "Running")

    with cols[1]:
        st.metric("Duration", format_duration(started_at))

    with cols[2]:
        st.metric("Files Added", current_run.get("num_added", 0))

    with cols[3]:
        st.metric("Files Updated", current_run.get("num_updated", 0))

    with cols[4]:
        st.metric("Transferred", format_bytes(current_run.get("bytes_transferred", 0)))

    # Additional metrics row
    cols2 = st.columns(3)

    with cols2[0]:
        errors = current_run.get("errors", 0)
        st.metric(
            "Errors",
            errors,
            delta=f"-{errors}" if errors > 0 else None,
            delta_color="inverse" if errors > 0 else "off",
        )

    with cols2[1]:
        is_process_running = current_run.get("is_process_running", False)
        st.metric("Process", "Active" if is_process_running else "Waiting")

    with cols2[2]:
        st.metric("Run ID", run_id)

    # Log output
    st.markdown("---")
    st.subheader("📋 Live Activity Log")

    # Get new logs
    logs_response = api.get_run_logs(run_id, since=st.session_state.last_line, limit=50)

    if logs_response:
        new_logs = logs_response.get("logs", [])
        next_line = logs_response.get("next_line", st.session_state.last_line)
        is_live = logs_response.get("is_live", False)

        # Accumulate new logs
        if new_logs:
            st.session_state.accumulated_logs.extend(new_logs)
            st.session_state.last_line = next_line

            # Keep only last 500 logs in memory
            if len(st.session_state.accumulated_logs) > 500:
                st.session_state.accumulated_logs = st.session_state.accumulated_logs[-500:]

        # Show live indicator
        if is_live:
            st.caption("🟢 Live - logs update automatically")
        else:
            st.caption("📁 Reading from log file")

    # Display logs in a container with scrolling
    log_container = st.container(height=400)

    with log_container:
        logs_to_show = st.session_state.accumulated_logs

        if not show_all_logs:
            # Filter to only show important levels
            logs_to_show = [
                log
                for log in logs_to_show
                if log.get("level", "").lower() in ["error", "warning", "notice"]
                or log.get("object", "")  # Show file operations
            ]

        if logs_to_show:
            # Show logs in reverse order (newest first)
            for log in reversed(logs_to_show[-100:]):  # Show last 100 logs
                render_log_entry(log)
        else:
            st.info("Waiting for log output...")

    # Log stats
    total_logs = len(st.session_state.accumulated_logs)
    error_logs = len(
        [l for l in st.session_state.accumulated_logs if l.get("level", "").lower() == "error"]
    )
    warning_logs = len(
        [l for l in st.session_state.accumulated_logs if l.get("level", "").lower() == "warning"]
    )

    st.caption(f"Total: {total_logs} logs | Errors: {error_logs} | Warnings: {warning_logs}")

# Auto-refresh logic
if auto_refresh:
    time.sleep(2)
    st.rerun()
else:
    # Manual refresh button when auto-refresh is off
    st.markdown("---")
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

