"""Live Dashboard view for MasCloner console."""

from __future__ import annotations

import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_bytes,
        format_duration,
        format_iso_time,
        render_hero_bar,
        render_status_pill,
    )
except ImportError:
    from api_client import APIClient
    from components.theme import (
        format_bytes,
        format_duration,
        format_iso_time,
        render_hero_bar,
        render_status_pill,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()

# 1. Header & Hero Bar
st.title("⚡ Live Dashboard")
render_hero_bar(api)

current_run = api.get_current_run_snapshot()
schedule = api.get_schedule_settings()
is_running = bool(current_run)
sched_enabled = schedule.enabled if schedule else False

# 2. In-Progress Alert Banner (if running)
if current_run is not None:
    run_id = current_run.id
    started_at = current_run.started_at
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
            stop_resp = api.stop_run(current_run.id)
            if stop_resp and stop_resp.get("success"):
                st.warning(f"Stop signal sent to Run #{current_run.id}.")
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
            result = api.set_schedule_paused(True)
            if result.success:
                st.toast(result.message, icon="⏸️")
                st.rerun()
            else:
                st.error(f"Unable to pause schedule: {result.message}")
    else:
        if st.button(
            "▶️ Resume Schedule",
            help="Enable automated interval syncs",
            use_container_width=True,
        ):
            result = api.set_schedule_paused(False)
            if result.success:
                st.toast(result.message, icon="▶️")
                st.rerun()
            else:
                st.error(f"Unable to resume schedule: {result.message}")

st.divider()

# 4. Active Sync Route & Endpoint Verification Card
paths = api.get_sync_paths() or {}
gdrive_src = paths.get("gdrive_src") or "/"
nc_dest_path = paths.get("nc_dest_path") or "/"
current_route_paths = {"gdrive_src": gdrive_src, "nc_dest_path": nc_dest_path}

route_col_header, route_col_action = st.columns([3, 1])
with route_col_header:
    st.subheader("🔄 Active Sync Route")
    st.caption("The permanent Google Drive to Nextcloud synchronization pathway")

with route_col_action:
    if st.button("⚡ Verify Endpoints", help="Probe both Google Drive and Nextcloud WebDAV to verify paths exist and are accessible", use_container_width=True):
        with st.spinner("Probing Google Drive & Nextcloud...", show_time=True):
            verification_result = api.verify_sync_route()
            if verification_result:
                st.session_state.route_verification = {
                    "paths": current_route_paths,
                    "result": verification_result.model_dump(),
                }
            else:
                st.error("Unable to verify the configured sync route.")

# Check session state verification or fallback to endpoint status
cached_verification = st.session_state.get("route_verification")
verification = (
    cached_verification.get("result")
    if isinstance(cached_verification, dict)
    and cached_verification.get("paths") == current_route_paths
    else None
)

card_col1, card_col2 = st.columns(2)

with card_col1:
    with st.container(border=True):
        st.markdown("#### 📁 Google Drive Source")
        st.markdown(f"**Path**: `{gdrive_src}`")
        st.markdown("**Remote Target**: `gdrive:`")
        if verification:
            source = verification["source"]
            if source["path_ok"]:
                st.success(f"🟢 **Endpoint Verified**: {source['message']}")
            else:
                st.error(f"🔴 **Verification Failed**: {source['message']}")
        else:
            gdrive_status = api.get_google_drive_endpoint_status()
            if gdrive_status and gdrive_status.configured:
                st.markdown("🟢 **Status**: Authenticated & Connected")
            else:
                st.markdown("🔴 **Status**: Disconnected / Expired")

with card_col2:
    with st.container(border=True):
        st.markdown("#### ☁️ Nextcloud Destination")
        st.markdown(f"**Path**: `{nc_dest_path}`")
        st.markdown("**Remote Target**: `ncwebdav:`")
        if verification:
            destination = verification["destination"]
            if destination["path_ok"]:
                st.success(f"🟢 **Endpoint Verified**: {destination['message']}")
            else:
                st.error(f"🔴 **Verification Failed**: {destination['message']}")
        else:
            nc_status = api.get_nextcloud_endpoint_status()
            if nc_status and nc_status.configured:
                st.markdown("🟢 **Status**: WebDAV Configured")
            else:
                st.markdown("🔴 **Status**: Not Configured")

st.divider()

# 5. Last Completed Sync Summary
st.subheader("🏁 Last Sync Execution")
recent_runs = api.get_recent_runs(limit=1) or []

if not recent_runs:
    st.info("No sync runs recorded yet. Click 'Sync Now' above to trigger your first run.")
else:
    last_run = recent_runs[0]
    run_id = last_run.id
    status = last_run.status
    status_pill = render_status_pill(status)
    started_at = last_run.started_at
    finished_at = last_run.finished_at
    duration = last_run.duration_seconds
    bytes_trans = last_run.bytes_transferred
    mutations = last_run.mutation_count
    error_msg = last_run.message

    last_col1, last_col2, last_col3, last_col4 = st.columns(4)
    with last_col1:
        st.metric("Latest Execution", f"Run #{run_id}", delta=status.upper(), border=True)
        st.markdown(status_pill)
    with last_col2:
        st.metric("Completed At", format_iso_time(finished_at or started_at), border=True)
    with last_col3:
        st.metric("Duration / Volume", format_duration(duration), f"{format_bytes(bytes_trans)} synced", border=True)
    with last_col4:
        st.metric("Files Mutated", f"{mutations} files", border=True)

    if error_msg:
        st.error(f"**Run Details**: {error_msg}")
    if last_run.errors:
        st.error(f"**Errors recorded**: {last_run.errors}")

    if st.button("📋 View Full Details in Run History", use_container_width=False):
        st.switch_page("pages/history.py")
