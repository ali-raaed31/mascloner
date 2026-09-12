"""
MasCloner Streamlit Web UI

Main entry point for the web interface.
"""

import streamlit as st
from typing import Dict, Any, Optional
from datetime import datetime
from api_client import APIClient

# Configure Streamlit page
st.set_page_config(
    page_title="Home - MasCloner",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': "MasCloner - Automated Google Drive to Nextcloud sync"
    }
)

# Initialize API client
@st.cache_resource
def get_api_client():
    return APIClient()

api = get_api_client()

# Sidebar Navigation
st.sidebar.title("🔄 MasCloner")
st.sidebar.markdown("---")

# Check API connection
def check_api_connection():
    """Check if API is available."""
    status = api.get_status()
    if status:
        st.sidebar.success("✅ API Connected")
        return True
    else:
        st.sidebar.error("❌ API Disconnected")
        st.sidebar.markdown("Please ensure the API server is running:")
        st.sidebar.code("python -m app.api.main")
        return False

# Display connection status
api_connected = check_api_connection()

# Main content
st.title("🏠 MasCloner Home")
st.markdown("**One-way sync from Google Drive to Nextcloud**")
st.markdown("Welcome to MasCloner! Monitor your sync status and manage your automated file synchronization.")

if not api_connected:
    st.error("Cannot connect to MasCloner API. Please start the API server.")
    st.code("cd /srv/mascloner && python -m app.api.main")
    st.stop()

# System Status Overview
status = api.get_status()
if status:
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        scheduler_running = status.get("scheduler_running", False)
        st.metric(
            "🔄 Scheduler",
            "🟢 Running" if scheduler_running else "🔴 Stopped",
            delta="Active" if scheduler_running else "Inactive"
        )
    
    with col2:
        remotes = status.get("remotes_configured", {})
        gdrive_ok = remotes.get("gdrive", False)
        nextcloud_ok = remotes.get("nextcloud", False)
        both_ok = gdrive_ok and nextcloud_ok
        st.metric(
            "🔗 Remotes",
            "🟢 Connected" if both_ok else "🟡 Partial" if (gdrive_ok or nextcloud_ok) else "🔴 Disconnected",
            delta=f"GDrive: {'✓' if gdrive_ok else '✗'} | Nextcloud: {'✓' if nextcloud_ok else '✗'}"
        )
    
    with col3:
        last_sync = status.get("last_sync")
        if last_sync:
            try:
                dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                last_sync_str = dt.strftime("%m/%d %H:%M")
                time_ago = datetime.now() - dt.replace(tzinfo=None)
                if time_ago.days > 0:
                    delta_str = f"{time_ago.days}d ago"
                elif time_ago.seconds > 3600:
                    delta_str = f"{time_ago.seconds//3600}h ago"
                else:
                    delta_str = f"{time_ago.seconds//60}m ago"
            except:
                last_sync_str = "Unknown"
                delta_str = "Error"
        else:
            last_sync_str = "Never"
            delta_str = "No syncs yet"
        st.metric("📅 Last Sync", last_sync_str, delta=delta_str)
    
    with col4:
        total_runs = status.get("total_runs", 0)
        config_valid = status.get("config_valid", False)
        st.metric(
            "📈 Total Runs", 
            str(total_runs),
            delta="✓ Config OK" if config_valid else "⚠️ Config Issue"
        )

st.markdown("---")

# Recent Activity
st.subheader("📋 Recent Activity")

runs = api.get_runs(limit=5)  # Only show last 5 runs for home page
if runs and len(runs) > 0:
    for run in runs:
        # Create expandable run details
        run_id = run.get("id", "Unknown")
        run_status = run.get("status", "unknown")
        start_time = run.get("started_at", "Unknown")
        
        # Status icon and color
        if run_status == "success":
            status_icon = "✅"
            status_color = "green"
        elif run_status == "running":
            status_icon = "🔄"
            status_color = "blue"
        elif run_status == "failed":
            status_icon = "❌"
            status_color = "red"
        else:
            status_icon = "❓"
            status_color = "gray"
        
        # Format timestamp
        try:
            if start_time != "Unknown":
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                time_str = dt.strftime("%m/%d %H:%M:%S")
            else:
                time_str = "Unknown time"
        except:
            time_str = start_time
        
        # Run summary
        files_added = run.get("num_added", 0)
        files_updated = run.get("num_updated", 0)
        bytes_transferred = run.get("bytes_transferred", 0)
        error_count = run.get("errors", 0)
        
        # Format file size
        if bytes_transferred > 1024*1024:
            size_str = f"{bytes_transferred/1024/1024:.1f} MB"
        elif bytes_transferred > 1024:
            size_str = f"{bytes_transferred/1024:.1f} KB"
        else:
            size_str = f"{bytes_transferred} B"
        
        with st.expander(f"{status_icon} Run #{run_id} - {time_str} - {run_status.title()}", expanded=False):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Files Added", files_added)
            with col2:
                st.metric("Files Updated", files_updated)
            with col3:
                st.metric("Data Transferred", size_str)
            with col4:
                st.metric("Errors", error_count, delta="⚠️" if error_count > 0 else "✅")
else:
    st.info("🌟 No sync runs yet. Your first automatic sync will start soon, or you can trigger one manually below.")

st.markdown("---")

# Quick Actions
st.subheader("🚀 Quick Actions")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("🔄 Trigger Sync Now", type="primary", use_container_width=True):
        with st.spinner("Starting sync..."):
            result = api.trigger_sync()
            if result and result.get("success"):
                st.success("✅ Sync triggered successfully!")
                st.rerun()
            else:
                st.error("❌ Failed to trigger sync")

with col2:
    scheduler_running = status.get("scheduler_running", False) if status else False
    if scheduler_running:
        if st.button("⏸️ Pause Scheduler", use_container_width=True):
            result = api.stop_scheduler()
            if result and result.get("success"):
                st.success("✅ Scheduler paused!")
                st.rerun()
            else:
                st.error("❌ Failed to pause scheduler")
    else:
        if st.button("▶️ Resume Scheduler", use_container_width=True):
            result = api.start_scheduler()
            if result and result.get("success"):
                st.success("✅ Scheduler resumed!")
                st.rerun()
            else:
                st.error("❌ Failed to resume scheduler")

with col3:
    if st.button("📊 View All Runs", use_container_width=True):
        st.switch_page("pages/3_Runs_and_Events.py")

with col4:
    if st.button("⚙️ Settings", use_container_width=True):
        st.switch_page("pages/2_Settings.py")

# Navigation Help
st.markdown("---")

with st.expander("📖 Navigation Guide"):
    st.markdown("""
    **🏠 Home** - System overview and quick actions (this page)
    
    **⚙️ Settings** - Configure schedules, test connections, and manage system settings
    
    **📋 History** - View detailed sync run history and file events
    
    **🔧 Setup Wizard** - Initial configuration for Google Drive and Nextcloud
    
    """)

# Footer
st.markdown("---")
st.markdown("**MasCloner** - Automated Google Drive to Nextcloud sync")
