"""
MasCloner Schedule Configuration Page

Configure sync scheduling and timing parameters.
"""

import streamlit as st
import httpx
from typing import Dict, Any, Optional
import json

# Page config
st.set_page_config(
    page_title="Schedule - MasCloner",
    page_icon="⏰",
    layout="wide"
)

# Import API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit_app import APIClient

# Initialize API client
api = APIClient()

st.title("⏰ Sync Schedule Configuration")

# Check API connection
status = api.get("/status")
if not status:
    st.error("Cannot connect to MasCloner API")
    st.stop()

# Current scheduler status
st.header("📊 Current Status")
col1, col2 = st.columns(2)

with col1:
    scheduler_running = status.get("scheduler_running", False)
    status_color = "🟢" if scheduler_running else "🔴"
    st.metric("Scheduler Status", f"{status_color} {'Running' if scheduler_running else 'Stopped'}")

with col2:
    next_run = status.get("next_run")
    if next_run and scheduler_running:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(next_run.replace('Z', '+00:00'))
            next_run_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            next_run_str = "Unknown"
    else:
        next_run_str = "Not scheduled"
    st.metric("Next Sync", next_run_str)

st.markdown("---")

# Schedule Configuration
st.header("🛠️ Schedule Settings")

# Get current configuration
config = api.get("/config")
current_interval = 5  # Default
current_jitter = 20   # Default

if config:
    current_interval = config.get("sync_interval_min", 5)
    current_jitter = config.get("sync_jitter_sec", 20)

# Schedule configuration form
with st.form("schedule_config"):
    st.subheader("Sync Timing")
    
    col1, col2 = st.columns(2)
    
    with col1:
        interval_min = st.number_input(
            "Sync Interval (minutes)",
            min_value=1,
            max_value=1440,  # 24 hours
            value=current_interval,
            help="How often to run sync jobs (1-1440 minutes)"
        )
    
    with col2:
        jitter_sec = st.number_input(
            "Jitter (seconds)",
            min_value=0,
            max_value=300,  # 5 minutes
            value=current_jitter,
            help="Random delay to add/subtract from schedule (0-300 seconds)"
        )
    
    st.markdown("---")
    
    # Advanced settings
    st.subheader("Advanced Options")
    
    col1, col2 = st.columns(2)
    
    with col1:
        max_concurrent = st.number_input(
            "Max Concurrent Jobs",
            min_value=1,
            max_value=5,
            value=1,
            help="Maximum number of sync jobs to run simultaneously"
        )
    
    with col2:
        retry_attempts = st.number_input(
            "Retry Attempts",
            min_value=0,
            max_value=10,
            value=3,
            help="Number of times to retry failed syncs"
        )
    
    # Submit button
    submitted = st.form_submit_button("💾 Save Schedule Configuration", type="primary")
    
    if submitted:
        new_config = {
            "sync_interval_min": interval_min,
            "sync_jitter_sec": jitter_sec,
            "max_concurrent_jobs": max_concurrent,
            "retry_attempts": retry_attempts
        }
        
        with st.spinner("Saving configuration..."):
            result = api.post("/config/schedule", new_config)
            
            if result and result.get("status") == "success":
                st.success("✅ Schedule configuration saved successfully!")
                st.info("ℹ️ Restart the scheduler to apply new settings.")
                st.rerun()
            else:
                st.error("❌ Failed to save schedule configuration")

st.markdown("---")

# Schedule Controls
st.header("🎛️ Schedule Controls")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("▶️ Start Scheduler", type="primary", use_container_width=True):
        with st.spinner("Starting scheduler..."):
            result = api.post("/schedule/start", {})
            if result:
                st.success("✅ Scheduler started!")
                st.rerun()
            else:
                st.error("❌ Failed to start scheduler")

with col2:
    if st.button("⏸️ Pause Scheduler", use_container_width=True):
        with st.spinner("Pausing scheduler..."):
            result = api.post("/schedule/stop", {})
            if result:
                st.success("⏸️ Scheduler paused!")
                st.rerun()
            else:
                st.error("❌ Failed to pause scheduler")

with col3:
    if st.button("🔄 Restart Scheduler", use_container_width=True):
        with st.spinner("Restarting scheduler..."):
            # Stop then start
            stop_result = api.post("/schedule/stop", {})
            if stop_result:
                start_result = api.post("/schedule/start", {})
                if start_result:
                    st.success("🔄 Scheduler restarted!")
                    st.rerun()
                else:
                    st.error("❌ Failed to restart scheduler")
            else:
                st.error("❌ Failed to stop scheduler")

st.markdown("---")

# Schedule Information
st.header("ℹ️ Schedule Information")

st.subheader("How Scheduling Works")
st.markdown("""
**MasCloner** uses APScheduler to manage sync timing:

- **Interval**: How often sync jobs run (in minutes)
- **Jitter**: Random variation added to prevent exact timing patterns
- **Concurrent Jobs**: Usually kept at 1 to prevent conflicts
- **Retry Logic**: Failed syncs are automatically retried

**Example**: With 5-minute interval and 20-second jitter:
- Sync could run at: 10:05:15, 10:10:08, 10:15:22, etc.
- This prevents predictable patterns and reduces server load
""")

st.subheader("Recommended Settings")

settings_info = [
    {"Use Case": "Development/Testing", "Interval": "1-2 minutes", "Jitter": "10-20 seconds"},
    {"Use Case": "Light Usage", "Interval": "5-10 minutes", "Jitter": "20-30 seconds"},
    {"Use Case": "Normal Usage", "Interval": "15-30 minutes", "Jitter": "30-60 seconds"},
    {"Use Case": "Heavy Usage", "Interval": "60+ minutes", "Jitter": "60-120 seconds"}
]

import pandas as pd
df_settings = pd.DataFrame(settings_info)
st.table(df_settings)

# Current schedule preview
if scheduler_running:
    st.subheader("📅 Current Schedule Preview")
    st.info(f"⏰ Syncs every **{current_interval} minutes** ± **{current_jitter} seconds** jitter")
    
    if next_run:
        st.info(f"🕒 Next sync: **{next_run_str}**")

# Warning about changes
st.warning("⚠️ **Important**: Schedule changes require a scheduler restart to take effect.")

st.markdown("---")
st.markdown("💡 **Tip**: Use shorter intervals for active development, longer intervals for production.")
