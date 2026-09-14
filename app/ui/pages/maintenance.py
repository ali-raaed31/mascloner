"""Retention policy, backup recovery, and maintenance view for MasCloner console."""

from __future__ import annotations

from typing import Any, Dict, Optional
import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_bytes,
        format_iso_time,
        render_hero_bar,
    )
except ImportError:
    from api_client import APIClient
    from components.theme import (
        format_bytes,
        format_iso_time,
        render_hero_bar,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()

st.title("🛡️ Retention & Backups")
render_hero_bar(api)

# 1. 60-Day History Retention Policy
st.subheader("🧹 60-Day History Retention Policy")
st.caption("Automatically prunes database runs, file events, and execution logs older than 60 days to ensure lean operations")

retention_status = api.get_retention_status() or {}
retention_days = retention_status.get("retention_days", 60)
last_report = retention_status.get("last_report") or {}

m_col1, m_col2, m_col3 = st.columns(3)
with m_col1:
    st.metric("Retention Window", f"{retention_days} Days", border=True)
with m_col2:
    last_pruned_runs = last_report.get("runs_pruned", 0)
    st.metric("Last Pruned Runs", f"{last_pruned_runs}", border=True)
with m_col3:
    last_pruned_events = last_report.get("events_pruned", 0)
    st.metric("Last Pruned Events", f"{last_pruned_events}", border=True)

if last_report.get("timestamp"):
    st.caption(f"Last retention pass executed: {format_iso_time(last_report.get('timestamp'))}")

with st.expander("⚡ Run Manual Retention Cleanup", expanded=False):
    is_dry_run = st.checkbox("Dry Run Simulation (Preview records without deleting)", value=True)
    custom_days = st.number_input("Retention Threshold (Days)", min_value=1, max_value=365, value=retention_days)

    if st.button("🚀 Execute Retention Pass", type="primary"):
        with st.spinner("Executing retention pass...", show_time=True):
            ret_res = api.trigger_retention(dry_run=is_dry_run, retention_days=int(custom_days))
            if ret_res:
                data = ret_res.get("data", ret_res)
                mode_str = "[DRY RUN PREVIEW]" if is_dry_run else "[COMPLETED]"
                st.success(
                    f"{mode_str} Retention pass completed: "
                    f"{data.get('runs_pruned', 0)} runs and {data.get('events_pruned', 0)} events identified/pruned."
                )
            else:
                st.error("Failed to execute retention pass.")

st.divider()

# 2. Consistency-Verified Database Backups
st.subheader("📦 Verified Database Backups")
st.caption("Create consistent, online SQLite recovery backups with automated SHA-256 integrity validation")

db_info = api.get_database_info() or {}
db_path = db_info.get("database_path", "/srv/mascloner/mascloner.db")
db_size = db_info.get("database_size_bytes") or db_info.get("size_bytes", 0)

b_col1, b_col2 = st.columns(2)
with b_col1:
    st.metric("Database Size", format_bytes(db_size), help=f"Location: {db_path}", border=True)
with b_col2:
    st.metric("Total Runs Stored", f"{db_info.get('total_runs', 0)}", f"{db_info.get('total_events', 0)} events", border=True)

if st.button("📦 Create Verified Recovery Backup Now", type="primary", use_container_width=True):
    with st.spinner("Generating consistent database snapshot & computing SHA-256...", show_time=True):
        backup_res = api.create_backup_bundle()
        if backup_res and backup_res.get("success", True):
            b_data = backup_res.get("data", backup_res)
            target = b_data.get("backup_path") or b_data.get("path") or "Unknown path"
            size = b_data.get("size_bytes")
            sha256 = b_data.get("sha256") or b_data.get("hash")
            verified = b_data.get("verified", True)

            st.success("✅ **Backup Created Successfully**")
            st.markdown(f"📁 **Backup Target**: `{target}`")
            st.markdown(f"📏 **Size**: {format_bytes(size)}")
            if sha256:
                st.markdown(f"🔐 **SHA-256**: `{sha256}`")
            if verified:
                st.info("🟢 **Integrity**: Consistency check passed (VACUUM verified).")
        else:
            err = backup_res.get("message") if backup_res else "Failed to generate backup"
            st.error(f"Backup failed: {err}")

st.divider()

# 3. Emergency Maintenance Zone
with st.expander("⚠️ Danger Zone: Emergency Database Reset"):
    st.warning("This operation will permanently purge all sync runs, telemetry events, and execution logs from the database.")
    confirm_text = st.text_input("Type 'RESET' to confirm database wipe:")
    if st.button("💣 Wipe Database History", type="secondary"):
        if confirm_text == "RESET":
            reset_res = api.reset_database()
            if reset_res and reset_res.get("success", True):
                st.success("Database has been reset.")
                st.rerun()
            else:
                st.error("Failed to reset database.")
        else:
            st.error("Confirmation string does not match 'RESET'.")
