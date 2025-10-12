"""
MasCloner Setup Wizard Page

Smart guided setup flow that checks existing configurations.
"""

import streamlit as st
from typing import Dict, Any, Optional
import json
import logging
from components.google_drive_setup import GoogleDriveSetup
from components.setup_panels import (
    render_configuration_checklist,
    render_fully_configured_view,
)
from components.folder_picker import FolderPicker, PickerConfig

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
logger = logging.getLogger(__name__)
st.title("🧙‍♂️ MasCloner Setup Wizard")

notice = st.session_state.pop("setup_wizard_notice", None)
if notice:
    st.success(notice)


def prefill_folder_picker(state_key: str, remote_name: str, path: str) -> None:
    if not path:
        return
    segments = [segment.strip() for segment in path.split("/") if segment.strip()]
    if not segments:
        return
    breadcrumb_state = st.session_state.setdefault("breadcrumb_picker_state", {})
    state = breadcrumb_state.get(state_key)
    if not state or state.get("remote") != remote_name:
        state = {"remote": remote_name, "levels": [], "children_cache": {}}
        breadcrumb_state[state_key] = state
    state["levels"] = ["/".join(segments[: idx + 1]) for idx in range(len(segments))]

# Check API connection
status = api.get_status()
if not status:
    st.error("❌ Cannot connect to MasCloner API")
    st.stop()

# Quick navigation
col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("🏠 Home", use_container_width=True):
        st.switch_page("Home.py")
with col2:
    if st.button("⚙️ Settings", use_container_width=True):
        st.switch_page("pages/2_Settings.py")
with col3:
    if st.button("📋 History", use_container_width=True):
        st.switch_page("pages/3_Runs_and_Events.py")
with col4:
    if st.button("🌳 File Tree", use_container_width=True):
        st.switch_page("pages/5_File_Tree.py")

st.markdown("---")

# Check current configuration status
def check_configuration_status():
    """Check the current state of all configurations."""
    config_status = {
        "google_drive": False,
        "nextcloud": False,
        "sync_config": False,
        "all_configured": False
    }
    
    # Check Google Drive
    gdrive_status = api.get_google_drive_status()
    if gdrive_status and gdrive_status.get("configured"):
        config_status["google_drive"] = True
    
    # Check Nextcloud (from system status)
    remotes = status.get("remotes_configured", {})
    if remotes.get("nextcloud", False):
        config_status["nextcloud"] = True
    
    # Check sync configuration
    sync_config = api.get_config()
    if (sync_config and 
        sync_config.get("gdrive_remote") and 
        sync_config.get("gdrive_src") and 
        sync_config.get("nc_remote") and 
        sync_config.get("nc_dest_path")):
        config_status["sync_config"] = True
    
    # All configured if everything is set up
    config_status["all_configured"] = (
        config_status["google_drive"] and 
        config_status["nextcloud"] and 
        config_status["sync_config"]
    )
    
    return config_status

# Get configuration status
config_status = check_configuration_status()

reconfigure_mode = st.session_state.get("force_reconfigure", False)

if config_status["all_configured"] and not reconfigure_mode:
    render_fully_configured_view(api, config_status)
    st.markdown("---")
    if st.button("🔄 Change Sync Paths", type="secondary", use_container_width=True):
        st.session_state.force_reconfigure = True
        st.session_state.setup_step = 3
        st.session_state.setdefault("setup_data", {})
        st.experimental_rerun()
else:
    st.markdown("**Let's get MasCloner configured for your environment!**")
    render_configuration_checklist(config_status)
    
    st.markdown("---")
    status_for_flow = config_status.copy()
    if reconfigure_mode:
        status_for_flow["sync_config"] = False
    
    # Setup steps state management
    if "setup_step" not in st.session_state:
        # Determine starting step based on what's already configured
        if not status_for_flow["google_drive"]:
            st.session_state.setup_step = 1  # Start with Google Drive
        elif not status_for_flow["nextcloud"]:
            st.session_state.setup_step = 2  # Start with Nextcloud
        elif not status_for_flow["sync_config"]:
            st.session_state.setup_step = 3  # Start with sync paths
        else:
            st.session_state.setup_step = 4  # Final step
    else:
        # Auto-advance when a step has been completed
        if st.session_state.setup_step == 1 and status_for_flow["google_drive"]:
            st.session_state.setup_step = 2
        if st.session_state.setup_step == 2 and status_for_flow["nextcloud"]:
            st.session_state.setup_step = 3
        if st.session_state.setup_step == 3 and status_for_flow["sync_config"]:
            st.session_state.setup_step = 4
    
    if "setup_data" not in st.session_state:
        st.session_state.setup_data = {}
    
    # Progress calculation (only count steps that need to be done)
    total_steps = sum([
        1 if not status_for_flow["google_drive"] else 0,
        1 if not status_for_flow["nextcloud"] else 0, 
        1 if not status_for_flow["sync_config"] else 0,
        1  # Final step
    ])
    
    current_step = 0
    if status_for_flow["google_drive"]:
        current_step += 1
    if status_for_flow["nextcloud"]:
        current_step += 1
    if status_for_flow["sync_config"]:
        current_step += 1
    
    if st.session_state.setup_step == 1:
        current_step = 1
    elif st.session_state.setup_step == 2:
        current_step = 2 if not config_status["google_drive"] else 1
    elif st.session_state.setup_step == 3:
        current_step = total_steps - 1
    else:
        current_step = total_steps
    
    progress = current_step / total_steps if total_steps > 0 else 1.0
    st.progress(progress, text=f"Step {current_step} of {total_steps}")
    
    st.markdown("---")
    
    # Step 1: Google Drive Setup (only if not configured)
    if st.session_state.setup_step == 1 and not config_status["google_drive"]:
        st.header("📱 Step 1: Google Drive Configuration")
        st.markdown("Let's set up your Google Drive connection using OAuth.")
        
        # Use the Google Drive Setup component
        gdrive_setup = GoogleDriveSetup(api)
        setup_complete = gdrive_setup.render_setup_instructions()
        
        if setup_complete:
            st.success("✅ Google Drive configured successfully!")
            if st.button("➡️ Continue to Nextcloud Setup", type="primary"):
                st.session_state.setup_step = 2
                st.rerun()
    
    # Step 2: Nextcloud Setup (only if not configured)
    elif st.session_state.setup_step == 2 and not config_status["nextcloud"]:
        st.header("☁️ Step 2: Nextcloud Configuration")
        st.markdown("Now let's connect to your Nextcloud instance via WebDAV.")
        
        with st.form("nextcloud_setup"):
            st.subheader("🌐 Nextcloud Connection Details")
            
            col1, col2 = st.columns(2)
            
            with col1:
                nc_url = st.text_input(
                    "Nextcloud WebDAV URL",
                    placeholder="https://cloud.example.com/remote.php/dav/files/username/",
                    help="Full WebDAV URL including your username"
                )
                
                nc_user = st.text_input(
                    "Username",
                    placeholder="your_username",
                    help="Your Nextcloud username"
                )
            
            with col2:
                nc_pass = st.text_input(
                    "App Password",
                    type="password",
                    help="Nextcloud app password (recommended) or your regular password"
                )
                
                remote_name = st.text_input(
                    "Remote Name",
                    value="ncwebdav",
                    help="Name for this rclone remote"
                )
            
            if st.form_submit_button("🧪 Test & Save Nextcloud Connection", type="primary"):
                if nc_url and nc_user and nc_pass:
                    with st.spinner("Testing Nextcloud connection..."):
                        result = api.test_nextcloud_webdav(
                            url=nc_url,
                            user=nc_user,
                            password=nc_pass,
                            remote_name=remote_name
                        )
                        
                        if result and result.get("success"):
                            st.session_state.setup_data["nextcloud"] = {
                                "url": nc_url,
                                "user": nc_user,
                                "remote_name": remote_name
                            }
                            st.session_state.setup_step = 3
                            st.session_state["setup_wizard_notice"] = "✅ Nextcloud connection successful and remote created!"
                            st.rerun()
                        else:
                            error_msg = result.get("message", "Unknown error") if result else "Connection failed"
                            st.error(f"❌ Nextcloud connection failed: {error_msg}")
                else:
                    st.error("Please fill in all required fields")
    
    # Step 3: Sync Configuration (only if not configured)
    elif st.session_state.setup_step == 3 and not config_status["sync_config"]:
        st.header("🔄 Step 3: Sync Path Configuration")
        st.markdown("Configure which folders to sync between Google Drive and Nextcloud.")
        
        # Determine remote names to use for browsing
        sync_config_existing = api.get_config() or {}
        gdrive_status = api.get_google_drive_status() or {}
        gdrive_remote_name = (
            sync_config_existing.get("gdrive_remote")
            or st.session_state.setup_data.get("google_drive", {}).get("remote_name")
            or gdrive_status.get("remote_name")
            or "gdrive"
        )
        nextcloud_remote_name = (
            sync_config_existing.get("nc_remote")
            or st.session_state.setup_data.get("nextcloud", {}).get("remote_name")
            or "ncwebdav"
        )
        logger.info(
            "UI: using remotes gdrive='%s', nextcloud='%s' for sync configuration browse",
            gdrive_remote_name,
            nextcloud_remote_name
        )

        if sync_config_existing.get("gdrive_src"):
            prefill_folder_picker("gdrive_folder_picker", gdrive_remote_name, sync_config_existing.get("gdrive_src", ""))
        if sync_config_existing.get("nc_dest_path"):
            prefill_folder_picker("nextcloud_folder_picker", nextcloud_remote_name, sync_config_existing.get("nc_dest_path", ""))
        
        # Get available folders for selection
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📱 Google Drive Source")
            gdrive_picker = FolderPicker(
                api_client=api,
                state_key="gdrive_folder_picker",
                config=PickerConfig(
                    remote_name=gdrive_remote_name,
                    label="Google Drive",
                    placeholder="Shared drives/MyTeam/Documents"
                ),
            )
            selected_folder = gdrive_picker.render()
        
        with col2:
            st.subheader("☁️ Nextcloud Destination")
            nextcloud_picker = FolderPicker(
                api_client=api,
                state_key="nextcloud_folder_picker",
                config=PickerConfig(
                    remote_name=nextcloud_remote_name,
                    label="Nextcloud",
                    placeholder="Backups/GoogleDrive"
                ),
            )
            dest_folder = nextcloud_picker.render()

        with st.sidebar:
            st.markdown("### 📦 Sync Summary")
            st.markdown(
                f"- **Source remote**: `{gdrive_remote_name}`\n"
                f"- **Source path**: `{selected_folder or 'Not selected'}`"
            )
            st.markdown(
                f"- **Destination remote**: `{nextcloud_remote_name}`\n"
                f"- **Destination path**: `{dest_folder or 'Not selected'}`"
            )
        
        # Sync size estimation
        if selected_folder and dest_folder:
            st.markdown("---")
            
            if st.button("📊 Estimate Sync Size", use_container_width=True):
                with st.spinner("Calculating sync size..."):
                    source_path = f"{gdrive_remote_name}:{selected_folder}"
                    dest_path = f"{nextcloud_remote_name}:{dest_folder}"
                    logger.info(
                        "UI: estimating sync size source='%s' dest='%s'",
                        source_path,
                        dest_path
                    )
                    size_result = api.estimate_size(source_path, dest_path)
                    if size_result and (size_result.get("success") or size_result.get("status") == "success"):
                        file_count = size_result.get("file_count", 0)
                        size_mb = size_result.get("size_mb", 0)
                        st.info(f"📊 **Estimated sync**: {file_count:,} files, {size_mb:.1f} MB")
                    else:
                        logger.warning(
                            "UI: size estimation failed response=%s",
                            size_result
                        )
                        st.warning("Could not estimate sync size")
            
            # Save configuration
            st.markdown("---")
            
            if st.button("💾 Save Sync Configuration", type="primary", use_container_width=True):
                sync_config = {
                    "gdrive_remote": gdrive_remote_name,
                    "gdrive_src": selected_folder,
                    "nc_remote": nextcloud_remote_name, 
                    "nc_dest_path": dest_folder
                }
                
                with st.spinner("Saving configuration..."):
                    result = api.update_config(sync_config)
                    
                    if result and result.get("success"):
                        st.success("✅ Sync configuration saved!")
                        st.session_state.pop("force_reconfigure", None)
                        st.session_state.setup_step = 4
                        st.rerun()
                    else:
                        st.error("❌ Failed to save configuration")
    
    # Final step or if everything is configured
    else:
        st.header("🎉 Setup Complete!")
        st.success("**MasCloner is now fully configured and ready to use!**")
        
        st.markdown("""
        ### 🚀 What's Next?
        
        1. **🏠 Go to Home** - Monitor sync status and trigger manual syncs
        2. **⚙️ Visit Settings** - Adjust schedules and test connections  
        3. **📋 Check History** - View sync runs and file events
        4. **🌳 Explore File Tree** - Browse your synced files
        
        Your first automatic sync will start based on your schedule settings!
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🏠 Go to Home Dashboard", type="primary", use_container_width=True):
                # Clear setup state
                if "setup_step" in st.session_state:
                    del st.session_state.setup_step
                if "setup_data" in st.session_state:
                    del st.session_state.setup_data
                st.switch_page("Home.py")
        
        with col2:
            if st.button("⚙️ Open Settings", use_container_width=True):
                st.switch_page("pages/2_Settings.py")

# Help section
st.markdown("---")

with st.expander("❓ Setup Help & Troubleshooting"):
    st.markdown("""
    **Common Issues:**
    
    - **Google Drive not working**: Make sure you ran `rclone authorize "drive"` on a machine with a browser
    - **Nextcloud connection fails**: Verify your WebDAV URL and app password
    - **Folders not loading**: Check that remotes are properly configured and accessible
    
    **Need to start over?**
    
    If you're already configured, use the "Reset All Configuration" option above to start fresh.
    
    **Still having trouble?**
    
    Check the Settings page for connection testing and detailed error messages.
    """)
