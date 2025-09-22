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

from api_client import APIClient

# Initialize API client
api = APIClient()

st.title("📊 MasCloner Dashboard")

# Check API connection
status = api.get_status()
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
runs = api.get_runs()
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

# File Tree Section  
st.header("🌳 File Tree Preview")

# Get tree data
tree_data = api.get_tree()
if tree_data:
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("📁 Folders", tree_data["total_folders"])
    with col2:
        st.metric("📄 Files", tree_data["total_files"])
    with col3:
        root_status = tree_data["root"]["status"]
        status_emoji = {
            "synced": "✅",
            "pending": "⏳",
            "error": "❌",
            "conflict": "⚠️",
            "unknown": "❓"
        }.get(root_status, "❓")
        st.metric("📊 Status", f"{status_emoji} {root_status}")
    
    # Show recent folders/files
    if tree_data["root"].get("children"):
        st.subheader("📂 Recent Files & Folders")
        
        # Flatten tree to get recent items
        def get_recent_items(node, items=None, max_items=10):
            if items is None:
                items = []
            if len(items) >= max_items:
                return items
            
            if node.get("last_sync"):
                items.append({
                    "name": node["name"],
                    "type": node["type"],
                    "status": node["status"],
                    "last_sync": node.get("last_sync", ""),
                    "size": node.get("size", 0)
                })
            
            for child in node.get("children", []):
                get_recent_items(child, items, max_items)
            
            return items
        
        recent_items = get_recent_items(tree_data["root"])
        
        if recent_items:
            # Sort by last_sync (most recent first)
            recent_items.sort(key=lambda x: x["last_sync"], reverse=True)
            
            tree_preview_data = []
            for item in recent_items[:8]:  # Show top 8
                type_emoji = "📁" if item["type"] == "folder" else "📄"
                status_emoji = {
                    "synced": "✅",
                    "pending": "⏳", 
                    "error": "❌",
                    "conflict": "⚠️",
                    "unknown": "❓"
                }.get(item["status"], "❓")
                
                size_str = f"{item['size'] / 1024:.1f} KB" if item["size"] > 0 else "0 KB"
                last_sync = item["last_sync"][:16].replace("T", " ") if item["last_sync"] else "Never"
                
                tree_preview_data.append({
                    "Item": f"{type_emoji} {item['name']}",
                    "Status": f"{status_emoji} {item['status']}",
                    "Size": size_str,
                    "Last Sync": last_sync
                })
            
            df_tree = pd.DataFrame(tree_preview_data)
            st.dataframe(df_tree, use_container_width=True)
            
            # Link to full tree view
            if st.button("🌳 View Full File Tree", type="secondary"):
                st.switch_page("pages/6_File_Tree.py")
        else:
            st.info("No synced files yet.")
    else:
        st.info("No files in tree yet. Run a sync to see files appear here.")
else:
    st.info("File tree data not available. Ensure API is running.")

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
