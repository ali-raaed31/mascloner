"""Schedule and Engine performance configuration view for MasCloner console."""

from __future__ import annotations
from typing import Mapping

import streamlit as st

try:
    from app.ui.api_client import (
        APIClient,
        RclonePerformanceContract,
        ScheduleUpdateContract,
    )
    from app.ui.components.theme import (
        format_duration,
        format_iso_time,
        render_hero_bar,
    )
except ImportError:
    from api_client import APIClient, RclonePerformanceContract, ScheduleUpdateContract
    from components.theme import (
        format_duration,
        format_iso_time,
        render_hero_bar,
    )


def get_api() -> APIClient:
    return APIClient()


api = get_api()


def apply_engine_preset(
    current: RclonePerformanceContract, preset: Mapping[str, object]
) -> RclonePerformanceContract:
    """Apply profile values while preserving optional persisted engine settings."""
    return current.model_copy(update=preset)

st.title("⏱️ Schedule & Engine")
render_hero_bar(api)

# 1. Schedule Configuration Section
st.subheader("Automated Synchronization Cadence")
st.caption("Configure the durable interval and execution jitter for automated background runs")

sched_data = api.get_schedule_settings()
is_enabled = sched_data.enabled if sched_data else False
interval_mins = sched_data.interval_min if sched_data else 15
jitter_secs = sched_data.jitter_sec if sched_data else 0
next_run_iso = sched_data.next_run_time if sched_data else None

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
        res = api.save_schedule(
            ScheduleUpdateContract(
                enabled=toggle_enabled,
                interval_min=new_interval,
                jitter_sec=new_jitter,
            )
        )
        if res.success:
            st.success("Schedule configuration updated successfully!")
            st.rerun()
        else:
            st.error(f"Failed to update schedule: {res.message}")

st.divider()

# 2. Rclone Engine Performance & Concurrency Tuning
st.subheader("🚀 Rclone Engine Performance")
st.caption("Fine-tune transfer concurrency, checker threads, rate limits, and memory buffers")

rclone_cfg = api.get_rclone_performance() or RclonePerformanceContract(
    transfers=8,
    checkers=16,
    tpslimit=25,
    tpslimit_burst=1,
    buffer_size="32Mi",
    drive_chunk_size="64M",
    drive_upload_cutoff="128M",
    fast_list=False,
)
current_transfers = rclone_cfg.transfers
current_checkers = rclone_cfg.checkers
current_tpslimit = rclone_cfg.tpslimit
current_tpslimit_burst = rclone_cfg.tpslimit_burst
current_chunk = rclone_cfg.drive_chunk_size or "64M"
current_buffer = rclone_cfg.buffer_size or "32Mi"
current_upload_cutoff = rclone_cfg.drive_upload_cutoff or "128M"
current_fast_list = rclone_cfg.fast_list

PRESETS = {
    "Conservative (Low Resource)": {
        "transfers": 4,
        "checkers": 8,
        "tpslimit": 10,
        "tpslimit_burst": 1,
        "fast_list": True,
    },
    "Balanced (Recommended)": {
        "transfers": 8,
        "checkers": 16,
        "tpslimit": 25,
        "tpslimit_burst": 1,
        "fast_list": True,
    },
    "High-Throughput (Fast Network)": {
        "transfers": 16,
        "checkers": 32,
        "tpslimit": 50,
        "tpslimit_burst": 1,
        "fast_list": True,
    },
}

st.markdown("##### ⚡ 1-Click Engine Presets")
selected_preset = st.segmented_control(
    "Apply Engine Profile",
    options=list(PRESETS.keys()),
    default=None,
    key="engine_preset_segmented",
)
apply_preset = st.button(
    "Apply Selected Engine Profile",
    disabled=selected_preset not in PRESETS,
    key="apply_engine_preset",
)
if apply_preset and selected_preset in PRESETS:
    result = api.save_rclone_performance(
        apply_engine_preset(rclone_cfg, PRESETS[selected_preset])
    )
    if result.success:
        st.toast(f"Applied {selected_preset}")
        st.rerun()
    else:
        st.error(f"Failed to apply profile: {result.message}")

# Custom tuning form
with st.form("rclone_tuning_form"):
    st.markdown("##### 🛠️ Custom Parameter Tuning")
    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    with t_col1:
        new_transfers = st.number_input("Transfers (--transfers)", min_value=1, max_value=32, value=current_transfers)
    with t_col2:
        new_checkers = st.number_input("Checkers (--checkers)", min_value=1, max_value=64, value=current_checkers)
    with t_col3:
        new_tpslimit = st.number_input("Rate Limit TPS (--tpslimit)", min_value=1, max_value=100, value=current_tpslimit)
    with t_col4:
        new_tpslimit_burst = st.number_input(
            "Rate Limit Burst (--tpslimit-burst)",
            min_value=0,
            max_value=100,
            value=current_tpslimit_burst,
        )

    adv_col1, adv_col2, adv_col3, adv_col4 = st.columns(4)
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
    with adv_col4:
        cutoff_options = ["8M", "16M", "32M", "64M", "128M", "256M"]
        cutoff_idx = cutoff_options.index(current_upload_cutoff) if current_upload_cutoff in cutoff_options else 4
        new_upload_cutoff = st.selectbox(
            "Upload Cutoff (--drive-upload-cutoff)",
            options=cutoff_options,
            index=cutoff_idx,
        )

    save_rclone_btn = st.form_submit_button("💾 Save Custom Engine Parameters")

    if save_rclone_btn:
        res = api.save_rclone_performance(
            RclonePerformanceContract(
                transfers=int(new_transfers),
                checkers=int(new_checkers),
                tpslimit=int(new_tpslimit),
                tpslimit_burst=int(new_tpslimit_burst),
                drive_chunk_size=new_chunk,
                buffer_size=new_buffer,
                drive_upload_cutoff=new_upload_cutoff,
                fast_list=new_fast_list,
            )
        )
        if res.success:
            st.success("Rclone performance parameters updated!")
            st.rerun()
        else:
            st.error(f"Failed to update rclone configuration: {res.message}")
