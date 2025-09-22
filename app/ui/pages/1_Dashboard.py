"""
MasCloner Dashboard Page

Enhanced dashboard with detailed sync information and file tree view.
"""

import streamlit as st
import httpx
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json

# Page config
st.set_page_config(
    page_title="Dashboard - MasCloner",
    page_icon="📊",
    layout="wide"
)

# Import API client from main app
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit_app import APIClient, API_BASE_URL

# Initialize API client
api = APIClient()

st.title("📊 MasCloner Dashboard")

# Check API connection
status = api.get("/status")
if not status:
    st.error("Cannot connect to MasCloner API")
    st.stop()

# Status Overview
st.header("📈 System Status")
col1, col2, col3, col4 = st.columns(4)

with col1:
    scheduler_status = "🟢 Running" if status.get("scheduler_running") else "🔴 Stopped"
    st.metric("Scheduler", scheduler_status)

with col2:
    db_status = "🟢 Healthy" if status.get("database_ok") else "🔴 Error"
    st.metric("Database", db_status)

with col3:
    last_run = status.get("last_run")
    if last_run:
        try:
            dt = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
            last_run_str = dt.strftime("%m/%d %H:%M")
        except:
            last_run_str = "Unknown"
    else:
        last_run_str = "Never"
    st.metric("Last Sync", last_run_str)

with col4:
    next_run = status.get("next_run")
    if next_run:
        try:
            dt = datetime.fromisoformat(next_run.replace('Z', '+00:00'))
            next_run_str = dt.strftime("%H:%M")
        except:
            next_run_str = "Unknown"
    else:
        next_run_str = "Not scheduled"
    st.metric("Next Sync", next_run_str)

st.markdown("---")

# Recent Activity
st.header("🕒 Recent Activity")

# Get recent runs
runs = api.get("/runs")
if runs and len(runs) > 0:
    # Summary stats from recent runs
    recent_runs = runs[:5]  # Last 5 runs
    
    total_added = sum(run.get("num_added", 0) for run in recent_runs)
    total_updated = sum(run.get("num_updated", 0) for run in recent_runs)
    total_errors = sum(run.get("errors", 0) for run in recent_runs)
    total_bytes = sum(run.get("bytes", 0) for run in recent_runs)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Files Added (Last 5)", total_added)
    with col2:
        st.metric("Files Updated (Last 5)", total_updated)
    with col3:
        st.metric("Total Errors", total_errors, delta=-total_errors if total_errors > 0 else None)
    with col4:
        st.metric("Data Synced", f"{total_bytes / 1024 / 1024:.1f} MB" if total_bytes > 0 else "0 MB")
    
    # Detailed runs table
    st.subheader("📋 Run Details")
    
    runs_data = []
    for run in runs[:10]:
        status_emoji = {
            "success": "✅",
            "error": "❌", 
            "running": "🔄",
            "failed": "❌"
        }.get(run.get("status", "unknown"), "❓")
        
        runs_data.append({
            "Status": f"{status_emoji} {run.get('status', 'unknown').title()}",
            "Started": run.get("started_at", "Unknown")[:16] if run.get("started_at") else "Unknown",
            "Duration": run.get("duration_sec", "Unknown"),
            "Added": run.get("num_added", 0),
            "Updated": run.get("num_updated", 0),
            "Errors": run.get("errors", 0),
            "Size (MB)": round(run.get("bytes", 0) / 1024 / 1024, 2) if run.get("bytes") else 0
        })
    
    df = pd.DataFrame(runs_data)
    st.dataframe(df, use_container_width=True)
    
else:
    st.info("No sync runs yet. The first run will occur automatically when the scheduler is active.")

st.markdown("---")

# File Tree Section (Placeholder for now - will be enhanced in Phase 2.2)
st.header("🌳 File Tree (Preview)")
st.info("Enhanced file tree view with sync status will be available in the next update.")

# Get recent file events to show activity
events = api.get("/events")
if events and len(events) > 0:
    st.subheader("📂 Recent File Activity")
    
    events_data = []
    for event in events[:20]:  # Show last 20 events
        action_emoji = {
            "added": "➕",
            "updated": "📝",
            "skipped": "⏭️", 
            "error": "❌"
        }.get(event.get("action", "unknown"), "❓")
        
        events_data.append({
            "Action": f"{action_emoji} {event.get('action', 'unknown').title()}",
            "File": event.get("file_path", "Unknown"),
            "Size": f"{event.get('size', 0) / 1024:.1f} KB" if event.get("size") else "0 KB",
            "Time": event.get("timestamp", "Unknown")[:16] if event.get("timestamp") else "Unknown"
        })
    
    df_events = pd.DataFrame(events_data)
    st.dataframe(df_events, use_container_width=True)

else:
    st.info("No file events recorded yet.")

# Control Panel
st.markdown("---")
st.header("🎛️ Quick Controls")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("🔄 Trigger Sync", type="primary", use_container_width=True):
        with st.spinner("Triggering sync..."):
            result = api.post("/trigger", {})
            if result and result.get("status") == "success":
                st.success("✅ Sync triggered successfully!")
                st.rerun()
            else:
                st.error("❌ Failed to trigger sync")

with col2:
    if st.button("⏸️ Pause Scheduler", use_container_width=True):
        with st.spinner("Pausing scheduler..."):
            result = api.post("/schedule/stop", {})
            if result:
                st.success("⏸️ Scheduler paused!")
                st.rerun()

with col3:
    if st.button("▶️ Resume Scheduler", use_container_width=True):
        with st.spinner("Resuming scheduler..."):
            result = api.post("/schedule/start", {})
            if result:
                st.success("▶️ Scheduler resumed!")
                st.rerun()

with col4:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

# Auto-refresh option
st.markdown("---")
auto_refresh = st.checkbox("🔄 Auto-refresh every 30 seconds")
if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()
