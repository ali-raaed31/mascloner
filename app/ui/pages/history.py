"""Run History and File Audit view for MasCloner console."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_bytes,
        format_duration,
        format_iso_time,
        generate_run_csv,
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
        generate_run_csv,
        get_status_badge_meta,
        render_hero_bar,
        render_status_pill,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()

st.title("📋 Run History & Audit")
render_hero_bar(api)

# 1. Filters & Search Bar
filter_col1, filter_col2, filter_col3 = st.columns([1.5, 1, 1])

with filter_col1:
    status_choice = st.selectbox(
        "Filter by Status",
        options=["All Statuses", "completed", "failed", "aborted", "skipped", "running"],
        index=0,
    )

with filter_col2:
    limit_choice = st.selectbox(
        "Max Runs",
        options=[10, 25, 50, 100],
        index=1,
    )

with filter_col3:
    if st.button("🔄 Refresh History", use_container_width=True):
        st.rerun()

status_query = None if status_choice == "All Statuses" else status_choice
raw_runs = api.get_runs(limit=limit_choice, status=status_query)
if isinstance(raw_runs, dict):
    runs_list = raw_runs.get("runs", [])
elif isinstance(raw_runs, list):
    runs_list = raw_runs
else:
    runs_list = []

st.divider()

if not runs_list:
    st.info("No sync runs found matching the selected criteria.")
    st.stop()


ACTION_ICONS = {
    "added": "🟢 [ADDED]",
    "updated": "🔵 [UPDATED]",
    "deleted": "⚪ [DELETED]",
    "skipped": "⚪ [SKIPPED]",
    "conflict": "🟠 [CONFLICT]",
    "error": "🔴 [ERROR]",
}

# 2. Runs Matrix with Drilldown Expanders
for run in runs_list:
    run_id = run.get("id")
    status = run.get("status", "unknown")
    meta = get_status_badge_meta(status)
    started_at = run.get("started_at")
    finished_at = run.get("finished_at")
    bytes_trans = run.get("bytes_transferred", 0)
    num_added = run.get("num_added", 0)
    num_updated = run.get("num_updated", 0)
    errors = run.get("errors", 0)
    msg = run.get("message")

    # Compute duration
    duration_str = "-"
    if started_at and finished_at:
        try:
            st_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            fn_dt = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            duration_str = format_duration((fn_dt - st_dt).total_seconds())
        except Exception:
            duration_str = "-"

    header_title = f"{meta['icon']} Run #{run_id} — {meta['label']} | Started: {format_iso_time(started_at, include_relative=True)} | Transferred: {format_bytes(bytes_trans)}"

    with st.expander(header_title, expanded=(status in ("failed", "running"))):
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(f"**Status**: {render_status_pill(status)}")
            if msg:
                st.caption(f"Details: {msg}")
        with m2:
            st.markdown(f"**Started**: {format_iso_time(started_at, include_relative=False)}")
            st.markdown(f"**Finished**: {format_iso_time(finished_at, include_relative=False)}")
        with m3:
            st.markdown(f"**Duration**: {duration_str}")
            st.markdown(f"**Transferred**: {format_bytes(bytes_trans)}")
        with m4:
            st.markdown(f"**Mutations**: +{num_added} added, ~{num_updated} updated")
            if errors > 0:
                st.markdown(f"🔴 **Errors**: {errors}")
            else:
                st.markdown("🟢 **Errors**: 0")

        st.markdown("#### 📂 File Event Audit Trail")
        events_resp = api.get_run_events(run_id)
        events = events_resp.get("events", []) if isinstance(events_resp, dict) else (events_resp or [])

        if events:
            # Action summary counts
            added_cnt = sum(1 for e in events if e.get("action") == "added")
            updated_cnt = sum(1 for e in events if e.get("action") == "updated")
            error_cnt = sum(1 for e in events if e.get("action") == "error")
            conflict_cnt = sum(1 for e in events if e.get("action") == "conflict")
            skipped_cnt = sum(1 for e in events if e.get("action") == "skipped")

            st.caption(
                f"Total events: {len(events)} | Added: {added_cnt} | Updated: {updated_cnt} | "
                f"Conflicts: {conflict_cnt} | Errors: {error_cnt} | Skipped: {skipped_cnt}"
            )

            # Download CSV button
            csv_data = generate_run_csv(events)
            st.download_button(
                label=f"📥 Download Run #{run_id} Audit (CSV)",
                data=csv_data,
                file_name=f"mascloner_run_{run_id}_audit.csv",
                mime="text/csv",
                key=f"csv_btn_{run_id}",
            )

            # Display event table
            for ev in events:
                action = ev.get("action", "").lower()
                action_badge = ACTION_ICONS.get(action, f"[{action.upper()}]")
                file_path = ev.get("file_path", "")
                size_str = format_bytes(ev.get("file_size"))
                err_text = ev.get("message")

                if action == "error":
                    st.error(f"{action_badge} `{file_path}` ({size_str}) — Error: {err_text or 'Unspecified failure'}")
                elif action == "conflict":
                    st.warning(f"{action_badge} `{file_path}` ({size_str}) — Conflict: {err_text or 'Conflict detected'}")
                else:
                    st.markdown(f"{action_badge} `{file_path}` ({size_str})")
        else:
            st.info("No file mutations recorded for this run.")

        # Logs Drawer
        with st.expander(f"📜 View Raw Console Logs for Run #{run_id}"):
            logs_resp = api.get_run_logs(run_id, since=0, limit=200) or {}
            log_entries = logs_resp.get("logs", [])
            if log_entries:
                log_lines = []
                for entry in log_entries:
                    if isinstance(entry, dict):
                        log_lines.append(entry.get("raw") or entry.get("message") or str(entry))
                    else:
                        log_lines.append(str(entry))
                st.code("\n".join(log_lines), language="bash")
            else:
                st.caption("No log records available for this run.")
