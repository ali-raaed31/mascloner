"""
MasCloner Runs and Events Page

View detailed sync run history and file events.
"""

import streamlit as st
import httpx
import pandas as pd
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json

# Page config
st.set_page_config(
    page_title="Runs & Events - MasCloner",
    page_icon="📋",
    layout="wide"
)

# Import API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import APIClient

# Initialize API client
api = APIClient()

st.title("📋 Sync History & Events")
st.markdown("Track all your sync runs and file events in detail")

# Check API connection
status = api.get_status()
if not status:
    st.error("❌ Cannot connect to MasCloner API")
    st.stop()

# Quick navigation
col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("🏠 Home", use_container_width=True):
        st.switch_page("streamlit_app.py")
with col2:
    if st.button("⚙️ Settings", use_container_width=True):
        st.switch_page("pages/2_Settings.py")
with col3:
    if st.button("🔧 Setup Wizard", use_container_width=True):
        st.switch_page("pages/4_Setup_Wizard.py")
with col4:
    if st.button("🌳 File Tree", use_container_width=True):
        st.switch_page("pages/5_File_Tree.py")

st.markdown("---")

# Tabs for different views
tab1, tab2, tab3 = st.tabs(["📊 Runs Overview", "📂 File Events", "📈 Statistics"])

with tab1:
    st.header("📊 Sync Runs Overview")
    
    # Get runs data
    runs = api.get_runs()
    
    if not runs:
        st.info("No sync runs recorded yet.")
    else:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        total_runs = len(runs)
        successful_runs = len([r for r in runs if r.get("status") == "success"])
        failed_runs = len([r for r in runs if r.get("status") in ["error", "failed"]])
        total_files = sum(r.get("num_added", 0) + r.get("num_updated", 0) for r in runs)
        
        with col1:
            st.metric("Total Runs", total_runs)
        with col2:
            st.metric("Successful", successful_runs, delta=f"{(successful_runs/total_runs*100):.1f}%" if total_runs > 0 else "0%")
        with col3:
            st.metric("Failed", failed_runs, delta=f"-{(failed_runs/total_runs*100):.1f}%" if total_runs > 0 else "0%")
        with col4:
            st.metric("Total Files Synced", total_files)
        
        st.markdown("---")
        
        # Filters
        col1, col2, col3 = st.columns(3)
        
        with col1:
            status_filter = st.selectbox(
                "Filter by Status",
                ["All", "success", "error", "failed", "running"],
                index=0
            )
        
        with col2:
            date_filter = st.selectbox(
                "Filter by Date",
                ["All Time", "Last 24 Hours", "Last 7 Days", "Last 30 Days"],
                index=0
            )
        
        with col3:
            limit = st.number_input("Show Last N Runs", min_value=10, max_value=1000, value=50)
        
        # Filter runs
        filtered_runs = runs[:limit]  # Already ordered by API (newest first)
        
        if status_filter != "All":
            filtered_runs = [r for r in filtered_runs if r.get("status") == status_filter]
        
        if date_filter != "All Time":
            now = datetime.now()
            if date_filter == "Last 24 Hours":
                cutoff = now - timedelta(hours=24)
            elif date_filter == "Last 7 Days":
                cutoff = now - timedelta(days=7)
            elif date_filter == "Last 30 Days":
                cutoff = now - timedelta(days=30)
            
            filtered_runs = [
                r for r in filtered_runs 
                if r.get("started_at") and datetime.fromisoformat(r["started_at"]) > cutoff
            ]
        
        # Detailed runs table
        if filtered_runs:
            runs_data = []
            for run in filtered_runs:
                # Status with emoji
                status_emoji = {
                    "success": "✅",
                    "error": "❌",
                    "failed": "❌", 
                    "running": "🔄"
                }.get(run.get("status", "unknown"), "❓")
                
                # Duration calculation
                started = run.get("started_at")
                finished = run.get("finished_at")
                duration = "Unknown"
                
                if started and finished:
                    try:
                        start_dt = datetime.fromisoformat(started)
                        finish_dt = datetime.fromisoformat(finished)
                        duration_sec = (finish_dt - start_dt).total_seconds()
                        duration = f"{duration_sec:.1f}s"
                    except:
                        duration = "Unknown"
                elif started and run.get("status") == "running":
                    try:
                        start_dt = datetime.fromisoformat(started)
                        duration_sec = (datetime.now() - start_dt).total_seconds()
                        duration = f"{duration_sec:.1f}s (running)"
                    except:
                        duration = "Running"
                
                runs_data.append({
                    "ID": run.get("id"),
                    "Status": f"{status_emoji} {run.get('status', 'unknown').title()}",
                    "Started": started[:19] if started else "Unknown",
                    "Finished": finished[:19] if finished else ("Running" if run.get("status") == "running" else "Unknown"),
                    "Duration": duration,
                    "Added": run.get("num_added", 0),
                    "Updated": run.get("num_updated", 0),
                    "Errors": run.get("errors", 0),
                    "Size (MB)": round(run.get("bytes_transferred", 0) / 1024 / 1024, 2) if run.get("bytes_transferred") else 0
                })
            
            df_runs = pd.DataFrame(runs_data)
            st.dataframe(df_runs, use_container_width=True)
            
            # Download button
            csv_data = df_runs.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv_data,
                file_name=f"mascloner_runs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No runs match the selected filters.")

with tab2:
    st.header("📂 File Events")
    
    # Get events data
    events = api.get_events()
    
    if not events:
        st.info("No file events recorded yet.")
    else:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        total_events = len(events)
        added_files = len([e for e in events if e.get("action") == "added"])
        updated_files = len([e for e in events if e.get("action") == "updated"])
        error_events = len([e for e in events if e.get("action") == "error"])
        
        with col1:
            st.metric("Total Events", total_events)
        with col2:
            st.metric("Files Added", added_files)
        with col3:
            st.metric("Files Updated", updated_files)
        with col4:
            st.metric("Errors", error_events, delta=f"-{error_events}" if error_events > 0 else None)
        
        st.markdown("---")
        
        # Event filters
        col1, col2, col3 = st.columns(3)
        
        with col1:
            action_filter = st.selectbox(
                "Filter by Action",
                ["All", "added", "updated", "skipped", "error"],
                index=0
            )
        
        with col2:
            file_filter = st.text_input(
                "Filter by Filename",
                placeholder="Enter filename or pattern",
                help="Filter events by filename (case-insensitive)"
            )
        
        with col3:
            event_limit = st.number_input("Show Last N Events", min_value=10, max_value=1000, value=100)
        
        # Filter events
        filtered_events = events[:event_limit]
        
        if action_filter != "All":
            filtered_events = [e for e in filtered_events if e.get("action") == action_filter]
        
        if file_filter:
            filtered_events = [
                e for e in filtered_events 
                if file_filter.lower() in e.get("file_path", "").lower()
            ]
        
        # Events table
        if filtered_events:
            events_data = []
            for event in filtered_events:
                action_emoji = {
                    "added": "➕",
                    "updated": "📝",
                    "skipped": "⏭️",
                    "error": "❌"
                }.get(event.get("action", "unknown"), "❓")
                
                # Format file size
                size = event.get("size", 0)
                if size > 1024 * 1024:
                    size_str = f"{size / 1024 / 1024:.2f} MB"
                elif size > 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size} B"
                
                events_data.append({
                    "Action": f"{action_emoji} {event.get('action', 'unknown').title()}",
                    "File Path": event.get("file_path", "Unknown"),
                    "Size": size_str,
                    "Run ID": event.get("run_id", "Unknown"),
                    "Timestamp": event.get("timestamp", "Unknown")[:19] if event.get("timestamp") else "Unknown",
                    "Message": event.get("message", "")[:100] + "..." if len(event.get("message", "")) > 100 else event.get("message", "")
                })
            
            df_events = pd.DataFrame(events_data)
            st.dataframe(df_events, use_container_width=True)
            
            # Download button
            csv_data = df_events.to_csv(index=False)
            st.download_button(
                label="📥 Download Events as CSV",
                data=csv_data,
                file_name=f"mascloner_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No events match the selected filters.")

with tab3:
    st.header("📈 Statistics & Analytics")
    
    if not runs:
        st.info("No data available for statistics yet.")
    else:
        # Time-based statistics
        st.subheader("📊 Sync Performance Over Time")
        
        # Prepare data for charts
        chart_data = []
        for run in runs[-30:]:  # Last 30 runs
            if run.get("started_at"):
                chart_data.append({
                    "Date": run["started_at"][:10],
                    "Files Added": run.get("num_added", 0),
                    "Files Updated": run.get("num_updated", 0),
                    "Errors": run.get("errors", 0),
                    "Size (MB)": round(run.get("bytes_transferred", 0) / 1024 / 1024, 2)
                })
        
        if chart_data:
            df_chart = pd.DataFrame(chart_data)
            
            # Group by date and sum
            daily_stats = df_chart.groupby("Date").agg({
                "Files Added": "sum",
                "Files Updated": "sum", 
                "Errors": "sum",
                "Size (MB)": "sum"
            }).reset_index()
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("📁 Files Synced by Day")
                st.bar_chart(daily_stats.set_index("Date")[["Files Added", "Files Updated"]])
            
            with col2:
                st.subheader("💾 Data Volume by Day")
                st.line_chart(daily_stats.set_index("Date")["Size (MB)"])
        
        st.markdown("---")
        
        # File type analysis
        if events:
            st.subheader("📄 File Type Analysis")
            
            file_types = {}
            for event in events:
                if event.get("action") in ["added", "updated"]:
                    file_path = event.get("file_path", "")
                    if "." in file_path:
                        ext = file_path.split(".")[-1].lower()
                        file_types[ext] = file_types.get(ext, 0) + 1
            
            if file_types:
                # Top 10 file types
                sorted_types = sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:10]
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Chart
                    type_df = pd.DataFrame(sorted_types, columns=["Extension", "Count"])
                    st.bar_chart(type_df.set_index("Extension"))
                
                with col2:
                    # Table
                    st.table(type_df)
        
        st.markdown("---")
        
        # Error analysis
        st.subheader("❌ Error Analysis")
        
        error_events = [e for e in events if e.get("action") == "error"]
        
        if error_events:
            error_messages = {}
            for event in error_events:
                msg = event.get("message", "Unknown error")
                # Simplify error message for grouping
                simplified = msg[:50] + "..." if len(msg) > 50 else msg
                error_messages[simplified] = error_messages.get(simplified, 0) + 1
            
            # Top errors
            sorted_errors = sorted(error_messages.items(), key=lambda x: x[1], reverse=True)[:10]
            
            error_df = pd.DataFrame(sorted_errors, columns=["Error Message", "Count"])
            st.table(error_df)
        else:
            st.success("✅ No errors recorded!")
        
        st.markdown("---")
        
        # Performance metrics
        st.subheader("⚡ Performance Metrics")
        
        # Calculate averages
        successful_runs = [r for r in runs if r.get("status") == "success"]
        
        if successful_runs:
            avg_duration = sum(r.get("duration_sec", 0) for r in successful_runs) / len(successful_runs)
            avg_files = sum(r.get("num_added", 0) + r.get("num_updated", 0) for r in successful_runs) / len(successful_runs)
            avg_size = sum(r.get("bytes", 0) for r in successful_runs) / len(successful_runs) / 1024 / 1024
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Avg Duration", f"{avg_duration:.1f}s")
            with col2:
                st.metric("Avg Files/Run", f"{avg_files:.1f}")
            with col3:
                st.metric("Avg Size/Run", f"{avg_size:.2f} MB")

# Auto-refresh controls
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()

with col2:
    auto_refresh = st.checkbox("🔄 Auto-refresh every 60 seconds")

if auto_refresh:
    import time
    time.sleep(60)
    st.rerun()
