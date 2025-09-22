"""
MasCloner Setup Wizard Page

Guided setup flow for initial configuration.
"""

import streamlit as st
import httpx
from typing import Dict, Any, Optional
import json
from components.google_drive_setup import GoogleDriveSetup

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

from api_client import APIClient

# Initialize API client
api = APIClient()

st.title("🧙‍♂️ MasCloner Setup Wizard")
st.markdown("Welcome! This wizard will help you configure MasCloner for first-time use.")

# Check API connection
status = api.get_status()
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

# Step 2: Google Drive Setup
elif st.session_state.setup_step == 2:
    st.header("📁 Google Drive Setup")
    
    # Initialize the Google Drive setup component
    gdrive_setup = GoogleDriveSetup(api)
    
    # Check if already configured via API
    status_response = api.get_google_drive_status()
    is_configured = status_response and status_response.get("configured", False)
    
    if is_configured:
        st.success("✅ Google Drive is already configured!")
        
        # Show configuration details
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Remote Name", "gdrive")
            st.metric("Status", "Configured")
        with col2:
            if status_response.get("scope"):
                st.metric("Access Level", status_response["scope"])
            if status_response.get("folders"):
                st.metric("Folders Found", len(status_response["folders"]))
        
        # Show some sample folders
        if status_response.get("folders"):
            st.write("**Sample folders found:**")
            for folder in status_response["folders"][:5]:
                st.write(f"📁 {folder}")
        
        # Test connection button
        if st.button("🔄 Test Connection Again"):
            with st.spinner("Testing Google Drive connection..."):
                result = api.test_google_drive_connection()
                if result and result.get("success"):
                    st.success("✅ Google Drive connection successful!")
                    if result.get("data", {}).get("folders"):
                        st.write("**Recent test - folders found:**")
                        for folder in result["data"]["folders"][:5]:
                            st.write(f"📁 {folder}")
                else:
                    st.error(f"❌ Connection failed: {result.get('message', 'Unknown error') if result else 'API error'}")
        
        # Mark as configured in session state
        st.session_state.setup_data["gdrive_configured"] = True
    
    else:
        # Render the Google Drive setup interface
        setup_success = gdrive_setup.render_setup_instructions()
        if setup_success:
            st.balloons()
            st.session_state.setup_data["gdrive_configured"] = True
            st.rerun()
    
    # Navigation
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 1
            st.rerun()
    
    with col2:
        if is_configured or st.session_state.setup_data.get("gdrive_configured"):
            if st.button("▶️ Next: Nextcloud Setup", type="primary", use_container_width=True):
                st.session_state.setup_step = 3
                st.rerun()
        else:
            st.button("▶️ Next (Complete Google Drive setup first)", disabled=True, use_container_width=True)

# Step 3: Nextcloud Setup
elif st.session_state.setup_step == 3:
    st.header("☁️ Nextcloud Setup")
    
    st.markdown("""
    Configure **Nextcloud WebDAV** access directly through this interface.
    We'll test the connection in real-time and create the rclone remote automatically.
    """)
    
    # Check if already configured
    if "nc_remote" in st.session_state.setup_data:
        st.success("✅ Nextcloud already configured!")
        
        # Show current config
        nc_url = st.session_state.setup_data.get("nc_webdav_url", "Unknown")
        nc_user = st.session_state.setup_data.get("nc_user", "Unknown")
        
        st.info(f"""
        **Configuration:**
        - Remote name: **{st.session_state.setup_data['nc_remote']}**
        - WebDAV URL: `{nc_url}`
        - Username: `{nc_user}`
        """)
        
        # Test connection button
        if st.button("🔄 Test Connection Again"):
            with st.spinner("Testing Nextcloud connection..."):
                result = api.test_nextcloud(st.session_state.setup_data['nc_remote'])
                if result and result.get("status") == "success":
                    st.success("✅ Nextcloud connection successful!")
                else:
                    error_msg = result.get("error", "Unknown error") if result else "API error"
                    st.error(f"❌ Connection failed: {error_msg}")
                    # Clear config to allow reconfiguration
                    for key in ["nc_remote", "nc_webdav_url", "nc_user", "nc_pass"]:
                        st.session_state.setup_data.pop(key, None)
                    st.rerun()
    
    else:
        # Setup form
        st.subheader("🛠️ Nextcloud Configuration")
        
        with st.form("nextcloud_setup"):
            # WebDAV URL
            st.markdown("**1. WebDAV URL**")
            nc_url = st.text_input(
                "Nextcloud WebDAV URL",
                placeholder="https://cloud.example.com/remote.php/dav/files/USERNAME/",
                help="Full WebDAV URL from your Nextcloud settings"
            )
            
            st.info("""
            💡 **How to find your WebDAV URL:**
            1. Log into your Nextcloud
            2. Go to **Settings** → **Personal** → **Security**
            3. Look for **WebDAV** section
            4. Copy the URL (usually ends with `/remote.php/dav/files/USERNAME/`)
            """)
            
            st.markdown("---")
            
            # Credentials
            st.markdown("**2. Authentication**")
            
            col1, col2 = st.columns(2)
            with col1:
                nc_user = st.text_input(
                    "Username",
                    placeholder="your-username",
                    help="Your Nextcloud username"
                )
            
            with col2:
                nc_pass = st.text_input(
                    "App Password",
                    type="password",
                    placeholder="xxxx-xxxx-xxxx-xxxx",
                    help="Use an App Password, not your regular password"
                )
            
            st.warning("""
            🔐 **Security Note:** Use an **App Password** instead of your regular password:
            1. Go to **Settings** → **Personal** → **Security**
            2. Scroll to **App passwords**
            3. Create a new app password for "MasCloner"
            4. Use the generated password above
            """)
            
            st.markdown("---")
            
            # Remote name
            st.markdown("**3. Remote Name**")
            nc_remote_name = st.text_input(
                "Remote Name",
                value="ncwebdav",
                help="Choose a name for this Nextcloud remote"
            )
            
            # Submit button
            submitted = st.form_submit_button("🧪 Test & Save Configuration", type="primary")
            
            if submitted:
                # Validate inputs
                if not all([nc_url, nc_user, nc_pass, nc_remote_name]):
                    st.error("❌ Please fill in all fields")
                elif not nc_url.startswith(("http://", "https://")):
                    st.error("❌ WebDAV URL must start with http:// or https://")
                elif not nc_url.endswith("/"):
                    st.error("❌ WebDAV URL should end with a forward slash (/)")
                else:
                    with st.spinner("Testing Nextcloud connection..."):
                        # Test connection via API
                        test_data = {
                            "url": nc_url,
                            "user": nc_user,
                            "pass": nc_pass,
                            "remote_name": nc_remote_name
                        }
                        
                        result = api.test_nextcloud_webdav(nc_url, nc_user, nc_pass, nc_remote_name)
                        
                        if result and result.get("success"):
                            st.success("✅ Nextcloud connection successful!")
                            st.success("✅ rclone remote created automatically!")
                            
                            # Save configuration
                            st.session_state.setup_data.update({
                                "nc_remote": nc_remote_name,
                                "nc_webdav_url": nc_url,
                                "nc_user": nc_user,
                                "nc_pass": nc_pass  # Will be encrypted by API
                            })
                            
                            st.balloons()
                            st.rerun()
                        else:
                            error_msg = result.get("message", "Unknown error") if result else "API error"
                            st.error(f"❌ Connection failed: {error_msg}")
                            
                            st.markdown("""
                            **Common issues:**
                            - Check WebDAV URL format
                            - Verify username and app password
                            - Ensure Nextcloud allows WebDAV access
                            - Check network connectivity
                            """)
    
    # Navigation
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 2
            st.rerun()
    
    with col2:
        if "nc_remote" in st.session_state.setup_data:
            if st.button("▶️ Next: Folder Selection", type="primary", use_container_width=True):
                st.session_state.setup_step = 4
                st.rerun()
        else:
            st.button("▶️ Next (Complete Nextcloud setup first)", disabled=True, use_container_width=True)

# Step 4: Folder Selection
elif st.session_state.setup_step == 4:
    st.header("📁 Folder Selection")
    
    st.markdown("""
    Now that both remotes are configured, choose which folders to sync.
    **After authentication**, you can browse and select the actual folders.
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📤 Google Drive Source")
        
        # Check if we can browse folders
        gdrive_remote = st.session_state.setup_data.get("gdrive_remote", "gdrive")
        
        if st.button("🔍 Browse Google Drive Folders"):
            with st.spinner("Loading Google Drive folders..."):
                folders = api.browse_folders(gdrive_remote)
                if folders and folders.get("status") == "success":
                    st.session_state["gdrive_folders"] = folders.get("folders", [])
                    st.success(f"✅ Found {len(folders.get('folders', []))} folders")
                else:
                    st.error("❌ Failed to browse folders. Check connection.")
        
        # Show folder selection
        if "gdrive_folders" in st.session_state:
            folder_options = ["(Root - sync everything)"] + st.session_state["gdrive_folders"]
            
            selected_folder = st.selectbox(
                "Select Source Folder",
                folder_options,
                help="Choose which Google Drive folder to sync"
            )
            
            if selected_folder == "(Root - sync everything)":
                gdrive_src = ""
            else:
                gdrive_src = selected_folder
        else:
            # Manual entry as fallback
            gdrive_src = st.text_input(
                "Source Path in Google Drive",
                value=st.session_state.setup_data.get("gdrive_src", ""),
                placeholder="Shared drives/Team/Documents",
                help="Path within Google Drive to sync FROM (leave empty for root)"
            )
            
            st.info("💡 Click 'Browse Google Drive Folders' above to select from available folders")
        
        st.markdown("""
        **Common paths:**
        - `Shared drives/Team Folder/Documents`
        - `My Drive/Projects`
        - `` (empty for entire Drive)
        """)
    
    with col2:
        st.subheader("📥 Nextcloud Destination")
        
        # Check if we can browse folders
        nc_remote = st.session_state.setup_data.get("nc_remote", "ncwebdav")
        
        if st.button("🔍 Browse Nextcloud Folders"):
            with st.spinner("Loading Nextcloud folders..."):
                folders = api.browse_folders(nc_remote)
                if folders and folders.get("status") == "success":
                    st.session_state["nc_folders"] = folders.get("folders", [])
                    st.success(f"✅ Found {len(folders.get('folders', []))} folders")
                else:
                    st.error("❌ Failed to browse folders. Check connection.")
        
        # Show folder selection
        if "nc_folders" in st.session_state:
            folder_options = st.session_state["nc_folders"] + ["+ Create New Folder"]
            
            selected_folder = st.selectbox(
                "Select Destination Folder",
                folder_options,
                help="Choose where to sync files in Nextcloud"
            )
            
            if selected_folder == "+ Create New Folder":
                nc_dest = st.text_input(
                    "New Folder Name",
                    placeholder="Backups/GoogleDrive",
                    help="Enter the path for the new folder"
                )
            else:
                nc_dest = selected_folder
        else:
            # Manual entry as fallback
            nc_dest = st.text_input(
                "Destination Path in Nextcloud",
                value=st.session_state.setup_data.get("nc_dest_path", ""),
                placeholder="Backups/GoogleDrive",
                help="Path within Nextcloud to sync TO"
            )
            
            st.info("💡 Click 'Browse Nextcloud Folders' above to select from existing folders")
        
        st.markdown("""
        **Examples:**
        - `Backups/GoogleDrive`
        - `Sync/Team`
        - `Documents/Archive`
        """)
    
    st.markdown("---")
    
    # Preview sync configuration
    if gdrive_src is not None and nc_dest:
        st.subheader("🔍 Sync Preview")
        
        source_path = f"{gdrive_remote}:{gdrive_src}" if gdrive_src else f"{gdrive_remote}:"
        dest_path = f"{nc_remote}:{nc_dest}"
        
        st.code(f"""
Sync Configuration:
  Source: {source_path}
  Destination: {dest_path}
  
This will copy files FROM Google Drive TO Nextcloud.
Files will be synced one-way (Google Drive → Nextcloud).
        """)
        
        # Folder size estimation (if available)
        if st.button("📊 Estimate Sync Size"):
            with st.spinner("Calculating folder sizes..."):
                size_info = api.estimate_size(source_path, dest_path)
                if size_info and size_info.get("status") == "success":
                    st.success(f"📁 Estimated size: {size_info.get('size_mb', 0)} MB ({size_info.get('file_count', 0)} files)")
                else:
                    st.warning("⚠️ Could not estimate size. This is normal for new setups.")
    
    # Navigation
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("◀️ Previous", use_container_width=True):
            st.session_state.setup_step = 3
            st.rerun()
    
    with col2:
        if nc_dest:  # At minimum, need destination path
            if st.button("▶️ Next: Performance Settings", type="primary", use_container_width=True):
                st.session_state.setup_data["gdrive_src"] = gdrive_src if gdrive_src else ""
                st.session_state.setup_data["nc_dest_path"] = nc_dest
                st.session_state.setup_step = 5
                st.rerun()
        else:
            st.button("▶️ Next (Select destination folder)", disabled=True, use_container_width=True)

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
                "gdrive_remote": setup_data.get("gdrive_remote", "gdrive"),
                "gdrive_src": setup_data.get("gdrive_src", ""),
                "nc_remote": setup_data.get("nc_remote", "ncwebdav"),
                "nc_dest_path": setup_data.get("nc_dest_path", "")
            }
            
            # Debug: Show what we're trying to save
            st.write("**Debug - Configuration to save:**")
            st.json(sync_config)
            
            sync_result = api.update_config(sync_config)
            
            if sync_result and sync_result.get("success"):
                # Skip performance config for now - start scheduler directly
                scheduler_result = api.start_scheduler()
                
                if scheduler_result:
                    st.success("🎉 Setup completed successfully!")
                    st.balloons()
                    
                    st.markdown("""
                    **✅ MasCloner is now configured and running!**
                    
                    What happens next:
                    - Sync scheduler is active and will run every 5 minutes
                    - Files will be automatically synced from Google Drive to Nextcloud
                    - Check the Dashboard for sync status and history
                    - Visit Settings to modify configuration anytime
                    """)
                    
                    # Reset wizard
                    if st.button("🏠 Go to Dashboard"):
                        st.session_state.setup_step = 1
                        st.session_state.setup_data = {}
                        st.switch_page("streamlit_app.py")
                else:
                    st.error("❌ Failed to start scheduler")
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
