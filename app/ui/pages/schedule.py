"""Schedule and Engine performance configuration view for MasCloner console."""

from __future__ import annotations

from typing import Any, Dict, Optional
import streamlit as st

try:
    from app.ui.api_client import APIClient
    from app.ui.components.theme import (
        format_duration,
        format_iso_time,
        render_hero_bar,
    )
except ImportError:
    from api_client import APIClient
    from components.theme import (
        format_duration,
        format_iso_time,
        render_hero_bar,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()

st.title("⏱️ Schedule & Engine")
render_hero_bar(api)

# 1. Schedule Configuration Section
st.subheader("Automated Synchronization Cadence")
st.caption("Configure the durable interval and execution jitter for automated background runs")

sched_data = api.get_schedule() or {}
is_enabled = sched_data.get("enabled", False)
interval_mins = int(sched_data.get("interval_minutes") or 15)
jitter_secs = int(sched_data.get("jitter_seconds") or 0)
next_run_iso = sched_data.get("next_run_time")

with st.form("schedule_form"):
    toggle_enabled = st.toggle("Enable Automated Background Schedule", value=is_enabled)
    
    col_int, col_jit = st.columns(2)
    with col_int:
        new_interval = st.slider(
            "Sync Interval (minutes)",
            min_value=1,
            max_value=1440,
            value=max(1, min(interval_mins, 1440)),
            step=1,
            help="How frequently MasCloner checks for changes and executes synchronization",
        )
    with col_jit:
        new_jitter = st.slider(
            "Random Jitter (seconds)",
            min_value=0,
            max_value=300,
            value=max(0, min(jitter_secs, 300)),
            step=5,
            help="Adds pseudo-random variance to avoid exact-millisecond thundering herds",
        )

    # Visual Jitter Window Preview
    min_secs = max(0, new_interval * 60 - new_jitter)
    max_secs = new_interval * 60 + new_jitter
    min_formatted = format_duration(min_secs)
    max_formatted = format_duration(max_secs)

    st.info(
        f"🎯 **Expected Launch Cadence**: Every `{new_interval}m` ± `{new_jitter}s` "
        f"(Runs execute between **{min_formatted}** and **{max_formatted}** apart)"
    )

    if next_run_iso and toggle_enabled:
        st.caption(f"Currently calculated next run: {format_iso_time(next_run_iso)}")

    save_sched_btn = st.form_submit_button("💾 Save Schedule Configuration", type="primary")

    if save_sched_btn:
        save_payload = {
            "enabled": toggle_enabled,
            "interval_minutes": new_interval,
            "jitter_seconds": new_jitter,
        }
        res = api.update_schedule(save_payload)
        if res and res.get("success", True):
            st.success("Schedule configuration updated successfully!")
            st.rerun()
        else:
            st.error("Failed to update schedule")

st.divider()

# 2. Rclone Engine Performance & Concurrency Tuning
st.subheader("🚀 Rclone Engine Performance")
st.caption("Fine-tune transfer concurrency, checker threads, rate limits, and memory buffers")

rclone_cfg = api.get_rclone_config() or {}
current_transfers = int(rclone_cfg.get("transfers") or 8)
current_checkers = int(rclone_cfg.get("checkers") or 16)
current_tpslimit = int(rclone_cfg.get("tpslimit") or 25)
current_chunk = rclone_cfg.get("drive_chunk_size") or "64M"
current_buffer = rclone_cfg.get("buffer_size") or "32Mi"
current_fast_list = bool(rclone_cfg.get("use_fast_list", True))

PRESETS = {
    "Conservative (Low Resource)": {
        "transfers": 4,
        "checkers": 8,
        "tpslimit": 10,
        "drive_chunk_size": "32M",
        "buffer_size": "16Mi",
        "use_fast_list": True,
    },
    "Balanced (Recommended)": {
        "transfers": 8,
        "checkers": 16,
        "tpslimit": 25,
        "drive_chunk_size": "64M",
        "buffer_size": "32Mi",
        "use_fast_list": True,
    },
    "High-Throughput (Fast Network)": {
        "transfers": 16,
        "checkers": 32,
        "tpslimit": 50,
        "drive_chunk_size": "128M",
        "buffer_size": "64Mi",
        "use_fast_list": True,
    },
}

st.markdown("##### ⚡ 1-Click Engine Presets")
p_col1, p_col2, p_col3 = st.columns(3)

with p_col1:
    if st.button("Apply Conservative Preset", use_container_width=True):
        api.update_rclone_config(PRESETS["Conservative (Low Resource)"])
        st.toast("Applied Conservative preset")
        st.rerun()

with p_col2:
    if st.button("Apply Balanced Preset", type="secondary", use_container_width=True):
        api.update_rclone_config(PRESETS["Balanced (Recommended)"])
        st.toast("Applied Balanced preset")
        st.rerun()

with p_col3:
    if st.button("Apply High-Throughput Preset", use_container_width=True):
        api.update_rclone_config(PRESETS["High-Throughput (Fast Network)"])
        st.toast("Applied High-Throughput preset")
        st.rerun()

# Custom tuning form
with st.form("rclone_tuning_form"):
    st.markdown("##### 🛠️ Custom Parameter Tuning")
    t_col1, t_col2, t_col3 = st.columns(3)
    with t_col1:
        new_transfers = st.number_input("Transfers (--transfers)", min_value=1, max_value=32, value=current_transfers)
    with t_col2:
        new_checkers = st.number_input("Checkers (--checkers)", min_value=1, max_value=64, value=current_checkers)
    with t_col3:
        new_tpslimit = st.number_input("Rate Limit TPS (--tpslimit)", min_value=0, max_value=100, value=current_tpslimit)

    adv_col1, adv_col2, adv_col3 = st.columns(3)
    with adv_col1:
        chunk_options = ["8M", "16M", "32M", "64M", "128M", "256M"]
        chunk_idx = chunk_options.index(current_chunk) if current_chunk in chunk_options else 3
        new_chunk = st.selectbox("Drive Chunk Size", options=chunk_options, index=chunk_idx, help="Must be a power of 2 >= 256K")
    with adv_col2:
        buffer_options = ["8Mi", "16Mi", "32Mi", "64Mi", "128Mi"]
        buf_idx = buffer_options.index(current_buffer) if current_buffer in buffer_options else 2
        new_buffer = st.selectbox("Buffer Size (--buffer-size)", options=buffer_options, index=buf_idx)
    with adv_col3:
        new_fast_list = st.checkbox("Fast List (--fast-list)", value=current_fast_list, help="Uses fewer API transactions by listing multiple files in memory")

    save_rclone_btn = st.form_submit_button("💾 Save Custom Engine Parameters")

    if save_rclone_btn:
        payload = {
            "transfers": int(new_transfers),
            "checkers": int(new_checkers),
            "tpslimit": int(new_tpslimit),
            "drive_chunk_size": new_chunk,
            "buffer_size": new_buffer,
            "use_fast_list": new_fast_list,
        }
        res = api.update_rclone_config(payload)
        if res and res.get("success", True):
            st.success("Rclone performance parameters updated!")
            st.rerun()
        else:
            st.error("Failed to update rclone configuration")
