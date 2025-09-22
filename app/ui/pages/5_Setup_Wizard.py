"""
MasCloner Setup Wizard Page

Guided setup flow for initial configuration.
"""

import streamlit as st
import httpx
from typing import Dict, Any, Optional
import json

# Page config
st.set_page_config(
    page_title="Setup Wizard - MasCloner",
    page_icon="🧙‍♂️",
    layout="wide"
)

# Import API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit_app import APIClient

# Initialize API client
api = APIClient()

st.title("🧙‍♂️ MasCloner Setup Wizard")
st.markdown("Welcome! This wizard will help you configure MasCloner for first-time use.")

# Check API connection
status = api.get("/status")
if not status:
    st.error("Cannot connect to MasCloner API")
    st.stop()

# Setup steps state management
if "setup_step" not in st.session_state:
    st.session_state.setup_step = 1

if "setup_data" not in st.session_state:
    st.session_state.setup_data = {}

# Progress indicator
progress = st.session_state.setup_step / 5
st.progress(progress, text=f"Step {st.session_state.setup_step} of 5")

st.markdown("---")

# Step 1: Welcome and Prerequisites
if st.session_state.setup_step == 1:
    st.header("👋 Welcome to MasCloner!")
    
    st.markdown("""
    **MasCloner** provides automated one-way sync from Google Drive to Nextcloud.
    
    Before we begin, please ensure you have:
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        ✅ **Google Drive Access**
        - Google account with Drive access
        - rclone Google Drive remote configured
        
        ✅ **Nextcloud Instance**  
        - Nextcloud server URL
        - Valid username and password
        - WebDAV access enabled
        """)
    
    with col2:
        st.markdown("""
        ✅ **Technical Requirements**
        - rclone installed and accessible
        - Network connectivity to both services
        - Sufficient storage space on Nextcloud
        
        ✅ **Permissions**
        - Write access to sync destination
        - Read access to Google Drive source
        """)
    
    st.markdown("---")
    
    ready = st.checkbox("✅ I have confirmed all prerequisites above")
    
    if ready:
        if st.button("▶️ Start Setup", type="primary"):
            st.session_state.setup_step = 2
            st.rerun()
    else:
        st.info("Please confirm all prerequisites before continuing.")

# Step 2: rclone Configuration
elif st.session_state.setup_step == 2:
    st.header("🔧 rclone Configuration")
    
    st.markdown("""
    **MasCloner** uses rclone to handle file transfers. You need to configure two remotes:
    1. **Google Drive remote** - for accessing your Drive files
    2. **Nextcloud WebDAV remote** - for uploading to Nextcloud
    """)
    
    tab1, tab2 = st.tabs(["📁 Google Drive", "☁️ Nextcloud"])
    
    with tab1:
        st.subheader("🔗 Google Drive Remote Setup")
        
        st.markdown("""
        **Create Google Drive remote:**
        
        1. Open terminal and run:
        ```bash
        rclone config create gdrive drive
        ```
        
        2. Follow the OAuth flow to authorize access
        3. Test the connection:
        ```bash
        rclone lsd gdrive:
        ```
        """)
        
        gdrive_remote = st.text_input(
            "Google Drive Remote Name",
            value="gdrive",
            help="Name you gave to your Google Drive remote in rclone"
        )
        
        if st.button("🧪 Test Google Drive Connection"):
            with st.spinner("Testing Google Drive connection..."):
                result = api.post("/test/gdrive", {"remote": gdrive_remote})
                if result and result.get("status") == "success":
                    st.success("✅ Google Drive connection successful!")
                    st.session_state.setup_data["gdrive_remote"] = gdrive_remote
                else:
                    error_msg = result.get("error", "Unknown error") if result else "API error"
                    st.error(f"❌ Google Drive connection failed: {error_msg}")
    
    with tab2:
        st.subheader("☁️ Nextcloud WebDAV Remote Setup")
        
        st.markdown("""
        **Create Nextcloud WebDAV remote:**
        
        1. Open terminal and run:
        ```bash
        rclone config create ncwebdav webdav \\
            url https://your-nextcloud.com/remote.php/dav/files/USERNAME/ \\
            vendor nextcloud \\
            user USERNAME \\
            pass PASSWORD
        ```
        
        2. Test the connection:
        ```bash
        rclone lsd ncwebdav:
        ```
        """)
        
        nc_remote = st.text_input(
            "Nextcloud Remote Name",
            value="ncwebdav",
            help="Name you gave to your Nextcloud WebDAV remote in rclone"
        )
        
        if st.button("🧪 Test Nextcloud Connection"):
            with st.spinner("Testing Nextcloud connection..."):
                result = api.post("/test/nextcloud", {"remote": nc_remote})
                if result and result.get("status") == "success":
                    st.success("✅ Nextcloud connection successful!")
                    st.session_state.setup_data["nc_remote"] = nc_remote
                else:
                    error_msg = result.get("error", "Unknown error") if result else "API error"
                    st.error(f"❌ Nextcloud connection failed: {error_msg}")
    
    st.markdown("---")
    
    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 1
            st.rerun()
    
    with col2:
        if ("gdrive_remote" in st.session_state.setup_data and 
            "nc_remote" in st.session_state.setup_data):
            if st.button("▶️ Next", type="primary", use_container_width=True):
                st.session_state.setup_step = 3
                st.rerun()
        else:
            st.button("▶️ Next (Test connections first)", disabled=True, use_container_width=True)

# Step 3: Source and Destination Paths
elif st.session_state.setup_step == 3:
    st.header("📁 Source & Destination Configuration")
    
    st.markdown("Configure which folders to sync between Google Drive and Nextcloud.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📤 Google Drive Source")
        
        gdrive_src = st.text_input(
            "Source Path in Google Drive",
            value=st.session_state.setup_data.get("gdrive_src", ""),
            placeholder="Shared drives/Team/Documents",
            help="Path within Google Drive to sync FROM (leave empty for root)"
        )
        
        st.markdown("""
        **Examples:**
        - `Shared drives/Team Folder/Documents`
        - `My Drive/Projects`
        - `` (empty for entire Drive)
        """)
    
    with col2:
        st.subheader("📥 Nextcloud Destination")
        
        nc_dest = st.text_input(
            "Destination Path in Nextcloud",
            value=st.session_state.setup_data.get("nc_dest_path", ""),
            placeholder="Backups/GoogleDrive",
            help="Path within Nextcloud to sync TO"
        )
        
        st.markdown("""
        **Examples:**
        - `Backups/GoogleDrive`
        - `Sync/Team`
        - `Documents/Archive`
        """)
    
    st.markdown("---")
    
    # Preview sync configuration
    if gdrive_src or nc_dest:
        st.subheader("🔍 Sync Preview")
        
        gdrive_remote = st.session_state.setup_data.get("gdrive_remote", "gdrive")
        nc_remote = st.session_state.setup_data.get("nc_remote", "ncwebdav")
        
        source_path = f"{gdrive_remote}:{gdrive_src}" if gdrive_src else f"{gdrive_remote}:"
        dest_path = f"{nc_remote}:{nc_dest}" if nc_dest else f"{nc_remote}:"
        
        st.code(f"""
Sync Configuration:
  Source: {source_path}
  Destination: {dest_path}
  
This will copy files FROM Google Drive TO Nextcloud.
        """)
    
    # Validation and navigation
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 2
            st.rerun()
    
    with col2:
        if nc_dest:  # At minimum, need destination path
            if st.button("▶️ Next", type="primary", use_container_width=True):
                st.session_state.setup_data["gdrive_src"] = gdrive_src
                st.session_state.setup_data["nc_dest_path"] = nc_dest
                st.session_state.setup_step = 4
                st.rerun()
        else:
            st.button("▶️ Next (Enter destination path)", disabled=True, use_container_width=True)

# Step 4: Performance and Schedule Settings
elif st.session_state.setup_step == 4:
    st.header("⚙️ Performance & Schedule Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📅 Sync Schedule")
        
        interval_min = st.number_input(
            "Sync Interval (minutes)",
            min_value=1,
            max_value=1440,
            value=5,
            help="How often to run sync jobs"
        )
        
        jitter_sec = st.number_input(
            "Jitter (seconds)",
            min_value=0,
            max_value=300,
            value=20,
            help="Random delay to prevent exact timing patterns"
        )
    
    with col2:
        st.subheader("🚀 Performance Settings")
        
        transfers = st.number_input(
            "Parallel Transfers",
            min_value=1,
            max_value=20,
            value=4,
            help="Number of files to transfer simultaneously"
        )
        
        checkers = st.number_input(
            "Parallel Checkers",
            min_value=1,
            max_value=50,
            value=8,
            help="Number of checkers to run in parallel"
        )
    
    st.markdown("---")
    
    # Recommended settings
    st.subheader("💡 Recommended Settings")
    
    setting_type = st.radio(
        "Choose your usage pattern:",
        ["Light (Personal use)", "Normal (Small team)", "Heavy (Large team)"],
        index=1
    )
    
    if setting_type == "Light (Personal use)":
        rec_interval, rec_transfers, rec_checkers = 15, 2, 4
    elif setting_type == "Normal (Small team)":
        rec_interval, rec_transfers, rec_checkers = 5, 4, 8
    else:  # Heavy
        rec_interval, rec_transfers, rec_checkers = 3, 8, 16
    
    if st.button("📋 Apply Recommended Settings"):
        interval_min = rec_interval
        transfers = rec_transfers
        checkers = rec_checkers
        st.rerun()
    
    st.info(f"💡 Recommended for {setting_type}: {rec_interval}min interval, {rec_transfers} transfers, {rec_checkers} checkers")
    
    # Navigation
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 3
            st.rerun()
    
    with col2:
        if st.button("▶️ Next", type="primary", use_container_width=True):
            st.session_state.setup_data.update({
                "sync_interval_min": interval_min,
                "sync_jitter_sec": jitter_sec,
                "transfers": transfers,
                "checkers": checkers
            })
            st.session_state.setup_step = 5
            st.rerun()

# Step 5: Review and Complete Setup
elif st.session_state.setup_step == 5:
    st.header("🎯 Review Configuration")
    
    st.markdown("Please review your configuration before completing setup.")
    
    # Configuration summary
    setup_data = st.session_state.setup_data
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📁 Sync Configuration")
        st.code(f"""
Google Drive Remote: {setup_data.get('gdrive_remote', 'gdrive')}
Source Path: {setup_data.get('gdrive_src', '(root)')}

Nextcloud Remote: {setup_data.get('nc_remote', 'ncwebdav')}
Destination Path: {setup_data.get('nc_dest_path', '')}
        """)
    
    with col2:
        st.subheader("⚙️ Settings")
        st.code(f"""
Sync Interval: {setup_data.get('sync_interval_min', 5)} minutes
Jitter: {setup_data.get('sync_jitter_sec', 20)} seconds
Transfers: {setup_data.get('transfers', 4)}
Checkers: {setup_data.get('checkers', 8)}
        """)
    
    st.markdown("---")
    
    # Final configuration and save
    st.subheader("🔧 Complete Setup")
    
    if st.button("💾 Save Configuration & Start MasCloner", type="primary", use_container_width=True):
        with st.spinner("Saving configuration..."):
            # Save sync configuration
            sync_config = {
                "gdrive_remote": setup_data.get("gdrive_remote"),
                "gdrive_src": setup_data.get("gdrive_src", ""),
                "nc_remote": setup_data.get("nc_remote"),
                "nc_dest_path": setup_data.get("nc_dest_path")
            }
            
            sync_result = api.post("/config", sync_config)
            
            if sync_result and sync_result.get("status") == "success":
                # Save performance configuration
                perf_config = {
                    "sync_interval_min": setup_data.get("sync_interval_min"),
                    "sync_jitter_sec": setup_data.get("sync_jitter_sec"),
                    "transfers": setup_data.get("transfers"),
                    "checkers": setup_data.get("checkers")
                }
                
                perf_result = api.post("/config/performance", perf_config)
                
                if perf_result and perf_result.get("status") == "success":
                    # Start scheduler
                    scheduler_result = api.post("/schedule/start", {})
                    
                    if scheduler_result:
                        st.success("🎉 Setup completed successfully!")
                        st.balloons()
                        
                        st.markdown("""
                        **✅ MasCloner is now configured and running!**
                        
                        What happens next:
                        - Sync scheduler is active and will run every {interval} minutes
                        - Files will be automatically synced from Google Drive to Nextcloud
                        - Check the Dashboard for sync status and history
                        - Visit Settings to modify configuration anytime
                        """.format(interval=setup_data.get("sync_interval_min", 5)))
                        
                        # Reset wizard
                        if st.button("🏠 Go to Dashboard"):
                            st.session_state.setup_step = 1
                            st.session_state.setup_data = {}
                            st.switch_page("streamlit_app.py")
                    else:
                        st.error("❌ Failed to start scheduler")
                else:
                    st.error("❌ Failed to save performance configuration")
            else:
                st.error("❌ Failed to save sync configuration")
    
    st.markdown("---")
    
    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 4
            st.rerun()
    
    with col2:
        if st.button("🔄 Restart Setup"):
            st.session_state.setup_step = 1
            st.session_state.setup_data = {}
            st.rerun()

# Footer
st.markdown("---")
st.markdown("**MasCloner Setup Wizard** - Automated Google Drive to Nextcloud sync configuration")
