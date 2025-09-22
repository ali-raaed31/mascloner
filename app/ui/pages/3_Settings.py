"""
MasCloner Settings Page

Configure sync sources, destinations, and rclone parameters.
"""

import streamlit as st
import httpx
from typing import Dict, Any, Optional
import json

# Page config
st.set_page_config(
    page_title="Settings - MasCloner",
    page_icon="⚙️",
    layout="wide"
)

# Import API client
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import APIClient

# Initialize API client
api = APIClient()

st.title("⚙️ MasCloner Settings")

# Check API connection
status = api.get_status()
if not status:
    st.error("Cannot connect to MasCloner API")
    st.stop()

# Get current configuration
config = api.get_config()
if not config:
    st.error("Failed to load configuration")
    st.stop()

# Sync Source/Destination Configuration
st.header("🔗 Sync Configuration")

with st.form("sync_config"):
    st.subheader("📁 Source (Google Drive)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        gdrive_remote = st.text_input(
            "Google Drive Remote Name",
            value=config.get("gdrive_remote", "gdrive"),
            help="rclone remote name for Google Drive"
        )
    
    with col2:
        gdrive_src = st.text_input(
            "Source Path",
            value=config.get("gdrive_src", ""),
            placeholder="Shared drives/Team/Folder",
            help="Path within Google Drive to sync from"
        )
    
    st.markdown("---")
    
    st.subheader("📤 Destination (Nextcloud)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        nc_remote = st.text_input(
            "Nextcloud Remote Name",
            value=config.get("nc_remote", "ncwebdav"),
            help="rclone remote name for Nextcloud WebDAV"
        )
    
    with col2:
        nc_dest_path = st.text_input(
            "Destination Path", 
            value=config.get("nc_dest_path", ""),
            placeholder="Backups/GoogleDrive",
            help="Path within Nextcloud to sync to"
        )
    
    # WebDAV Configuration
    st.markdown("---")
    st.subheader("🌐 WebDAV Settings")
    
    nc_webdav_url = st.text_input(
        "WebDAV URL",
        value=config.get("nc_webdav_url", ""),
        placeholder="https://cloud.example.com/remote.php/dav/files/USERNAME/",
        help="Full WebDAV URL for Nextcloud"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        nc_user = st.text_input(
            "Username",
            value=config.get("nc_user", ""),
            help="Nextcloud username"
        )
    
    with col2:
        nc_pass = st.text_input(
            "Password",
            type="password",
            help="Nextcloud password (will be encrypted)"
        )
    
    # Submit button
    submitted = st.form_submit_button("💾 Save Sync Configuration", type="primary")
    
    if submitted:
        new_config = {
            "gdrive_remote": gdrive_remote,
            "gdrive_src": gdrive_src,
            "nc_remote": nc_remote,
            "nc_dest_path": nc_dest_path,
            "nc_webdav_url": nc_webdav_url,
            "nc_user": nc_user
        }
        
        # Only include password if provided
        if nc_pass:
            new_config["nc_pass"] = nc_pass
        
        with st.spinner("Saving configuration..."):
            result = api.post("/config", new_config)
            
            if result and result.get("status") == "success":
                st.success("✅ Sync configuration saved successfully!")
                st.rerun()
            else:
                st.error("❌ Failed to save sync configuration")

st.markdown("---")

# rclone Performance Settings
st.header("🚀 Performance Settings")

with st.form("performance_config"):
    st.subheader("rclone Parameters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        transfers = st.number_input(
            "Transfers",
            min_value=1,
            max_value=20,
            value=config.get("transfers", 4),
            help="Number of file transfers to run in parallel"
        )
        
        checkers = st.number_input(
            "Checkers",
            min_value=1, 
            max_value=50,
            value=config.get("checkers", 8),
            help="Number of checkers to run in parallel"
        )
    
    with col2:
        tpslimit = st.number_input(
            "TPS Limit",
            min_value=1,
            max_value=100,
            value=config.get("tpslimit", 10),
            help="Limit HTTP transactions per second"
        )
        
        bwlimit = st.text_input(
            "Bandwidth Limit",
            value=config.get("bwlimit", "0"),
            placeholder="0 (unlimited), 10M, 1G",
            help="Limit bandwidth (0 = unlimited)"
        )
    
    st.markdown("---")
    
    st.subheader("Google Drive Settings")
    
    drive_export = st.text_input(
        "Export Formats",
        value=config.get("drive_export_formats", "docx,xlsx,pptx"),
        help="Comma-separated list of export formats for Google Docs"
    )
    
    # Submit button
    perf_submitted = st.form_submit_button("💾 Save Performance Settings", type="primary")
    
    if perf_submitted:
        perf_config = {
            "transfers": transfers,
            "checkers": checkers,
            "tpslimit": tpslimit,
            "bwlimit": bwlimit,
            "drive_export_formats": drive_export
        }
        
        with st.spinner("Saving performance settings..."):
            result = api.post("/config/performance", perf_config)
            
            if result and result.get("status") == "success":
                st.success("✅ Performance settings saved successfully!")
                st.rerun()
            else:
                st.error("❌ Failed to save performance settings")

st.markdown("---")

# rclone Configuration Management
st.header("🔧 rclone Configuration")

st.subheader("Remote Status")

# Test rclone remotes
col1, col2 = st.columns(2)

with col1:
    if st.button("🧪 Test Google Drive Connection", use_container_width=True):
        with st.spinner("Testing Google Drive connection..."):
            result = api.post("/test/gdrive", {})
            if result and result.get("status") == "success":
                st.success("✅ Google Drive connection OK")
            else:
                error_msg = result.get("error", "Unknown error") if result else "API error"
                st.error(f"❌ Google Drive connection failed: {error_msg}")

with col2:
    if st.button("🧪 Test Nextcloud Connection", use_container_width=True):
        with st.spinner("Testing Nextcloud connection..."):
            result = api.post("/test/nextcloud", {})
            if result and result.get("status") == "success":
                st.success("✅ Nextcloud connection OK")
            else:
                error_msg = result.get("error", "Unknown error") if result else "API error"
                st.error(f"❌ Nextcloud connection failed: {error_msg}")

st.markdown("---")

# Configuration Validation
st.header("✅ Configuration Validation")

if st.button("🔍 Validate All Settings", type="primary", use_container_width=True):
    with st.spinner("Validating configuration..."):
        result = api.validate_config()
        
        if result:
            if result.get("valid", False):
                st.success("✅ All configuration settings are valid!")
            else:
                st.error("❌ Configuration validation failed:")
                errors = result.get("errors", {})
                for category, error_list in errors.items():
                    st.error(f"**{category.title()}**: {', '.join(error_list)}")
        else:
            st.error("❌ Failed to validate configuration")

st.markdown("---")

# Configuration Export/Import
st.header("📋 Configuration Management")

col1, col2 = st.columns(2)

with col1:
    st.subheader("📤 Export Configuration")
    
    if st.button("📄 Download Config JSON", use_container_width=True):
        # Get sanitized config (no passwords)
        sanitized_config = {k: v for k, v in config.items() if "pass" not in k.lower()}
        
        st.download_button(
            label="💾 Download mascloner-config.json",
            data=json.dumps(sanitized_config, indent=2),
            file_name="mascloner-config.json",
            mime="application/json",
            use_container_width=True
        )

with col2:
    st.subheader("📥 Import Configuration")
    
    uploaded_file = st.file_uploader(
        "Upload Configuration JSON",
        type=['json'],
        help="Upload a previously exported configuration file"
    )
    
    if uploaded_file is not None:
        try:
            imported_config = json.load(uploaded_file)
            
            if st.button("📥 Import Configuration", use_container_width=True):
                with st.spinner("Importing configuration..."):
                    result = api.post("/config/import", imported_config)
                    
                    if result and result.get("status") == "success":
                        st.success("✅ Configuration imported successfully!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to import configuration")
        
        except json.JSONDecodeError:
            st.error("❌ Invalid JSON file")

st.markdown("---")

# Help and Documentation
st.header("❓ Help & Documentation")

with st.expander("🔗 rclone Remote Setup"):
    st.markdown("""
    **Setting up Google Drive remote:**
    ```bash
    rclone config create gdrive drive
    ```
    
    **Setting up Nextcloud WebDAV remote:**
    ```bash
    rclone config create ncwebdav webdav \\
        url https://cloud.example.com/remote.php/dav/files/USERNAME/ \\
        vendor nextcloud \\
        user USERNAME \\
        pass PASSWORD
    ```
    """)

with st.expander("⚡ Performance Tuning"):
    st.markdown("""
    **Recommended settings by use case:**
    
    - **Light usage**: transfers=2, checkers=4, tpslimit=5
    - **Normal usage**: transfers=4, checkers=8, tpslimit=10  
    - **Heavy usage**: transfers=8, checkers=16, tpslimit=20
    
    **Bandwidth limiting examples:**
    - `10M` = 10 MB/s
    - `1G` = 1 GB/s
    - `0` = unlimited
    """)

with st.expander("🔒 Security Notes"):
    st.markdown("""
    **Important security information:**
    
    - Passwords are encrypted using Fernet encryption
    - Configuration files contain sensitive data
    - Use secure file permissions (0600) in production
    - Regular security updates recommended
    """)

st.markdown("---")
st.markdown("💡 **Tip**: Always test connections after changing configuration settings.")
