"""Live Dashboard view for MasCloner console."""

from __future__ import annotations

from datetime import datetime, timezone
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

# 1. Header & Hero Bar
st.title("⚡ Live Dashboard")
render_hero_bar(api)

current_run = api.get_current_run()
schedule = api.get_schedule() or {}
is_running = bool(current_run)
sched_enabled = schedule.get("enabled", False)

# 2. In-Progress Alert Banner (if running)
if is_running:
    run_id = current_run.get("id")
    started_at = current_run.get("started_at")
    col_msg, col_btn = st.columns([3, 1])
    with col_msg:
        st.info(f"🔄 **Sync Run #{run_id} is currently executing** (started {format_iso_time(started_at)})")
    with col_btn:
        if st.button("📡 Open Live Monitor", use_container_width=True, type="primary"):
            st.switch_page("pages/live_monitor.py")

# 3. Primary Operations Bar
st.subheader("Operational Controls")
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns(3)

with ctrl_col1:
    sync_btn_label = "⚡ Sync Now"
    if st.button(
        sync_btn_label,
        type="primary",
        disabled=is_running,
        help="Trigger an immediate one-way sync run from Google Drive to Nextcloud",
        use_container_width=True,
    ):
        resp = api.trigger_sync()
        if resp and resp.get("success"):
            st.toast("Sync triggered successfully!", icon="🚀")
            st.switch_page("pages/live_monitor.py")
        else:
            err_msg = resp.get("message") if resp else "Failed to trigger sync"
            st.error(f"Error starting sync: {err_msg}")

with ctrl_col2:
    if st.button(
        "🛑 Stop Sync",
        disabled=not is_running,
        help="Gracefully terminate the currently running sync process",
        use_container_width=True,
    ):
        if current_run:
            stop_resp = api.stop_run(current_run["id"])
            if stop_resp and stop_resp.get("success"):
                st.warning(f"Stop signal sent to Run #{current_run['id']}.")
            else:
                st.error("Failed to signal stop.")
            st.rerun()

with ctrl_col3:
    if sched_enabled:
        if st.button(
            "⏸️ Pause Schedule",
            help="Temporarily disable automated interval syncs",
            use_container_width=True,
        ):
            api.stop_schedule()
            st.toast("Automated schedule paused.", icon="⏸️")
            st.rerun()
    else:
        if st.button(
            "▶️ Resume Schedule",
            help="Enable automated interval syncs",
            use_container_width=True,
        ):
            api.start_schedule()
            st.toast("Automated schedule resumed.", icon="▶️")
            st.rerun()

st.divider()

# 4. Active Sync Route & Endpoint Verification Card
route_col_header, route_col_action = st.columns([3, 1])
with route_col_header:
    st.subheader("🔄 Active Sync Route")
    st.caption("The permanent Google Drive to Nextcloud synchronization pathway")

with route_col_action:
    if st.button("⚡ Verify Endpoints", help="Probe both Google Drive and Nextcloud WebDAV to verify paths exist and are accessible", use_container_width=True):
        with st.spinner("Probing Google Drive & Nextcloud..."):
            gdrive_res = api.test_google_drive_connection() or {}
            nc_res = api.test_nextcloud() or {}
            st.session_state.route_verification = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "gdrive_ok": gdrive_res.get("success", False),
                "gdrive_msg": gdrive_res.get("message", "Unknown status"),
                "nc_ok": nc_res.get("success", False),
                "nc_msg": nc_res.get("message", "Unknown status"),
            }

paths = api.get_sync_paths() or {}
gdrive_src = paths.get("gdrive_src") or "/"
nc_dest_path = paths.get("nc_dest_path") or "/"

# Check session state verification or fallback to endpoint status
verification = st.session_state.get("route_verification")

card_col1, card_col2 = st.columns(2)

with card_col1:
    with st.container(border=True):
        st.markdown("#### 📁 Google Drive Source")
        st.markdown(f"**Path**: `{gdrive_src}`")
        st.markdown("**Remote Target**: `gdrive:`")
        if verification:
            if verification["gdrive_ok"]:
                st.success(f"🟢 **Endpoint Verified**: {verification['gdrive_msg']}")
            else:
                st.error(f"🔴 **Verification Failed**: {verification['gdrive_msg']}")
        else:
            gdrive_status = api.get_google_drive_status() or {}
            if gdrive_status.get("connected"):
                st.markdown("🟢 **Status**: Authenticated & Connected")
            else:
                st.markdown("🔴 **Status**: Disconnected / Expired")

with card_col2:
    with st.container(border=True):
        st.markdown("#### ☁️ Nextcloud Destination")
        st.markdown(f"**Path**: `{nc_dest_path}`")
        st.markdown("**Remote Target**: `ncwebdav:`")
        if verification:
            if verification["nc_ok"]:
                st.success(f"🟢 **Endpoint Verified**: {verification['nc_msg']}")
            else:
                st.error(f"🔴 **Verification Failed**: {verification['nc_msg']}")
        else:
            nc_status = api.get_nextcloud_status() or {}
            if nc_status.get("configured"):
                st.markdown("🟢 **Status**: WebDAV Configured")
            else:
                st.markdown("🔴 **Status**: Not Configured")

if verification:
    st.caption(f"Last verified: {format_iso_time(verification['timestamp'], include_relative=True)}")

st.divider()

# 5. Last Completed Sync Summary
st.subheader("🏁 Last Sync Execution")
raw_recent = api.get_runs(limit=1)
if isinstance(raw_recent, list):
    recent_runs = raw_recent
elif isinstance(raw_recent, dict):
    recent_runs = raw_recent.get("runs", [])
else:
    recent_runs = []

if not recent_runs:
    st.info("No sync runs recorded yet. Click 'Sync Now' above to trigger your first run.")
else:
    last_run = recent_runs[0]
    run_id = last_run.get("id")
    status = last_run.get("status", "unknown")
    status_pill = render_status_pill(status)
    started_at = last_run.get("started_at")
    completed_at = last_run.get("completed_at")
    duration = last_run.get("duration")
    bytes_trans = last_run.get("bytes_transferred", 0)
    files_trans = last_run.get("files_transferred", 0)
    error_msg = last_run.get("error_message")

    last_col1, last_col2, last_col3, last_col4 = st.columns(4)
    with last_col1:
        st.metric("Latest Execution", f"Run #{run_id}", delta=status.upper(), border=True)
    with last_col2:
        st.metric("Completed At", format_iso_time(completed_at or started_at), border=True)
    with last_col3:
        st.metric("Duration / Volume", format_duration(duration), f"{format_bytes(bytes_trans)} synced", border=True)
    with last_col4:
        st.metric("Files Mutated", f"{files_trans} files", border=True)

    if error_msg:
        st.error(f"**Run Failure Details**: {error_msg}")

    if st.button("📋 View Full Details in Run History", use_container_width=False):
        st.switch_page("pages/history.py")
