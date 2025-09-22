"""
MasCloner Streamlit Web UI

Main entry point for the web interface.
"""

import streamlit as st
import httpx
import json
from typing import Dict, Any, Optional
from datetime import datetime

# Configure Streamlit page
st.set_page_config(
    page_title="MasCloner",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API Configuration
API_BASE_URL = "http://127.0.0.1:8787"

class APIClient:
    """Client for communicating with MasCloner API."""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        
    def get(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make GET request to API."""
        try:
            with httpx.Client() as client:
                response = client.get(f"{self.base_url}{endpoint}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            st.error(f"API Error: {e}")
            return None
    
    def post(self, endpoint: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make POST request to API."""
        try:
            with httpx.Client() as client:
                response = client.post(f"{self.base_url}{endpoint}", json=data)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            st.error(f"API Error: {e}")
            return None

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
    status = api.get("/status")
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
st.title("🔄 MasCloner Dashboard")
st.markdown("One-way sync from Google Drive to Nextcloud")

if not api_connected:
    st.error("Cannot connect to MasCloner API. Please start the API server.")
    st.code("cd /srv/mascloner && python -m app.api.main")
    st.stop()

# Get status information
status = api.get("/status")
if status:
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Scheduler Status",
            "Running" if status.get("scheduler_running") else "Stopped",
            delta=None
        )
    
    with col2:
        st.metric(
            "Database Status", 
            "OK" if status.get("database_ok") else "Error",
            delta=None
        )
    
    with col3:
        last_run = status.get("last_run")
        if last_run:
            # Parse and format last run time
            try:
                dt = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
                last_run_str = dt.strftime("%H:%M:%S")
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
                next_run_str = dt.strftime("%H:%M:%S")
            except:
                next_run_str = "Unknown"
        else:
            next_run_str = "Not scheduled"
        st.metric("Next Sync", next_run_str)

st.markdown("---")

# Recent Runs
st.subheader("📊 Recent Sync Runs")

runs = api.get("/runs")
if runs:
    if len(runs) == 0:
        st.info("No sync runs yet. The first run will occur automatically.")
    else:
        # Display recent runs in a table
        import pandas as pd
        
        runs_data = []
        for run in runs[:10]:  # Show last 10 runs
            runs_data.append({
                "ID": run.get("id"),
                "Status": run.get("status", "unknown").title(),
                "Started": run.get("started_at", "Unknown"),
                "Finished": run.get("finished_at", "Running" if run.get("status") == "running" else "Unknown"),
                "Files Added": run.get("num_added", 0),
                "Files Updated": run.get("num_updated", 0),
                "Errors": run.get("errors", 0),
                "Data (MB)": round(run.get("bytes", 0) / 1024 / 1024, 2) if run.get("bytes") else 0
            })
        
        df = pd.DataFrame(runs_data)
        st.dataframe(df, use_container_width=True)

st.markdown("---")

# Quick Actions
st.subheader("🚀 Quick Actions")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🔄 Trigger Sync Now", type="primary"):
        result = api.post("/trigger", {})
        if result:
            st.success("Sync triggered successfully!")
            st.rerun()

with col2:
    if st.button("⏸️ Pause Scheduler"):
        result = api.post("/schedule/stop", {})
        if result:
            st.success("Scheduler paused!")
            st.rerun()

with col3:
    if st.button("▶️ Resume Scheduler"):
        result = api.post("/schedule/start", {})
        if result:
            st.success("Scheduler resumed!")
            st.rerun()

# Footer
st.markdown("---")
st.markdown("**MasCloner** - Automated Google Drive to Nextcloud sync")
