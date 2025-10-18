"""
MasCloner Settings Page

Combined settings and schedule configuration with tabbed interface.
"""

import streamlit as st
from typing import Dict, Any, Optional
from datetime import datetime
import json
import pandas as pd

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
    st.error("❌ Cannot connect to MasCloner API")
    st.stop()

# Current system status banner
with st.container():
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        scheduler_running = status.get("scheduler_running", False)
        st.metric("🔄 Scheduler", "🟢 Running" if scheduler_running else "🔴 Stopped")
    
    with col2:
        remotes = status.get("remotes_configured", {})
        gdrive_ok = remotes.get("gdrive", False)
        nextcloud_ok = remotes.get("nextcloud", False)
        both_ok = gdrive_ok and nextcloud_ok
        st.metric("🔗 Remotes", "🟢 Connected" if both_ok else "🟡 Partial" if (gdrive_ok or nextcloud_ok) else "🔴 Disconnected")
    
    with col3:
        config_valid = status.get("config_valid", False)
        st.metric("✅ Config", "🟢 Valid" if config_valid else "🔴 Invalid")
    
    with col4:
        total_runs = status.get("total_runs", 0)
        st.metric("📊 Total Runs", str(total_runs))

st.markdown("---")

# Tabbed interface
tab1, tab2, tab3, tab4 = st.tabs(["⏰ Schedule", "🔧 Remote Testing", "🔑 OAuth Settings", "🛠️ System"])

# ======================
# TAB 1: SCHEDULE SETTINGS
# ======================
with tab1:
    st.header("📅 Sync Schedule Configuration")
    
    # Current schedule status
    col1, col2 = st.columns(2)
    
    with col1:
        next_run = status.get("next_run")
        if next_run and scheduler_running:
            try:
                dt = datetime.fromisoformat(next_run.replace('Z', '+00:00'))
                next_run_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                next_run_str = "Unknown"
        else:
            next_run_str = "Not scheduled"
        st.info(f"🕒 **Next sync**: {next_run_str}")
    
    with col2:
        last_sync = status.get("last_sync")
        if last_sync:
            try:
                dt = datetime.fromisoformat(last_sync.replace('Z', '+00:00'))
                last_sync_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                last_sync_str = "Unknown"
        else:
            last_sync_str = "Never"
        st.info(f"📅 **Last sync**: {last_sync_str}")
    
    st.markdown("---")
    
    # Schedule configuration form
    with st.form("schedule_config"):
        st.subheader("⏱️ Timing Settings")
        
        # Get current schedule
        schedule = api.get_schedule()
        current_interval = schedule.get("interval_min", 5) if schedule else 5
        current_jitter = schedule.get("jitter_sec", 20) if schedule else 20
        
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
        
        # Submit button
        schedule_submitted = st.form_submit_button("💾 Save Schedule Settings", type="primary")
        
        if schedule_submitted:
            new_schedule = {
                "interval_min": interval_min,
                "jitter_sec": jitter_sec
            }
            
            with st.spinner("Saving schedule..."):
                result = api.update_schedule(new_schedule)
                
                if result and result.get("success"):
                    st.success("✅ Schedule settings saved successfully!")
                    st.rerun()
                else:
                    st.error("❌ Failed to save schedule settings")
    
    st.markdown("---")
    
    # Schedule controls
    st.subheader("🎛️ Schedule Controls")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if scheduler_running:
            if st.button("⏸️ Pause Scheduler", use_container_width=True):
                with st.spinner("Pausing scheduler..."):
                    result = api.stop_scheduler()
                    if result and result.get("success"):
                        st.success("⏸️ Scheduler paused!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to pause scheduler")
        else:
            if st.button("▶️ Start Scheduler", type="primary", use_container_width=True):
                with st.spinner("Starting scheduler..."):
                    result = api.start_scheduler()
                    if result and result.get("success"):
                        st.success("✅ Scheduler started!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to start scheduler")
    
    with col2:
        if st.button("🔄 Trigger Sync Now", use_container_width=True):
            with st.spinner("Triggering sync..."):
                result = api.trigger_sync()
                if result and result.get("success"):
                    st.success("✅ Sync triggered successfully!")
                    st.rerun()
                else:
                    st.error("❌ Failed to trigger sync")
    
    with col3:
        if st.button("📊 View Sync History", use_container_width=True):
            st.switch_page("pages/3_Runs_and_Events.py")
    
    # Schedule information
    with st.expander("ℹ️ Schedule Information"):
        st.markdown("""
        **How Scheduling Works:**
        
        - **Interval**: How often sync jobs run (in minutes)
        - **Jitter**: Random variation added to prevent exact timing patterns
        - This prevents predictable patterns and reduces server load
        
        **Recommended Settings:**
        """)
        
        settings_info = [
            {"Use Case": "Development/Testing", "Interval": "1-2 minutes", "Jitter": "10-20 seconds"},
            {"Use Case": "Light Usage", "Interval": "5-10 minutes", "Jitter": "20-30 seconds"},
            {"Use Case": "Normal Usage", "Interval": "15-30 minutes", "Jitter": "30-60 seconds"},
            {"Use Case": "Heavy Usage", "Interval": "60+ minutes", "Jitter": "60-120 seconds"}
        ]
        
        df_settings = pd.DataFrame(settings_info)
        st.table(df_settings)

# ======================
# TAB 2: REMOTE TESTING
# ======================
with tab2:
    st.header("🔗 Remote Connection Testing")
    
    sync_config_values = api.get_config() or {}
    gdrive_status = api.get_google_drive_status() or {}
    gdrive_remote_name = (
        sync_config_values.get("gdrive_remote")
        or gdrive_status.get("remote_name")
        or "gdrive"
    )
    nextcloud_remote_name = (
        sync_config_values.get("nc_remote")
        or "ncwebdav"
    )
    
    # Google Drive testing
    st.subheader("📱 Google Drive")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if gdrive_status and gdrive_status.get("configured"):
            st.success(f"✅ Google Drive remote `{gdrive_remote_name}` is configured and connected")
            if gdrive_status.get("folders"):
                with st.expander("📁 Available folders (first 10)"):
                    for folder in gdrive_status["folders"][:10]:
                        st.write(f"📁 {folder}")
        else:
            st.warning("⚠️ Google Drive not configured. Use the Setup Wizard to configure it.")
    
    with col2:
        if st.button("🧪 Test Google Drive", use_container_width=True):
            with st.spinner("Testing Google Drive..."):
                result = api.test_google_drive_connection()
                if result and result.get("success"):
                    st.success("✅ Google Drive connection OK")
                    if result.get("data", {}).get("folders"):
                        st.info(f"Found {len(result['data']['folders'])} folders")
                else:
                    error_msg = result.get("message", "Unknown error") if result else "API error"
                    st.error(f"❌ Google Drive failed: {error_msg}")
    
    st.markdown("---")
    
    # Nextcloud testing  
    st.subheader("☁️ Nextcloud")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        if nextcloud_ok:
            st.success("✅ Nextcloud is configured and connected")
        else:
            st.warning("⚠️ Nextcloud not configured. Use the Setup Wizard to configure it.")
    
    with col2:
        if st.button("🧪 Test Nextcloud", use_container_width=True):
            with st.spinner("Testing Nextcloud..."):
                result = api.test_nextcloud(nextcloud_remote_name)
                if result and result.get("success"):
                    st.success("✅ Nextcloud connection OK")
                else:
                    error_msg = result.get("message", "Unknown error") if result else "API error"
                    st.error(f"❌ Nextcloud failed: {error_msg}")
    
    st.markdown("---")
    
    # Configuration management
    st.subheader("🔧 Configuration Management")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Validate All Settings", use_container_width=True):
            with st.spinner("Validating configuration..."):
                result = api.validate_config()
                
                if result:
                    if result.get("valid", False):
                        st.success("✅ All configuration settings are valid!")
                    else:
                        st.error("❌ Configuration validation failed")
                        if "errors" in result:
                            for error in result["errors"]:
                                st.error(f"• {error}")
                else:
                    st.error("❌ Failed to validate configuration")
    
    with col2:
        if st.button("🔄 Go to Setup Wizard", use_container_width=True):
            st.switch_page("pages/4_Setup_Wizard.py")

# ======================
# TAB 3: OAUTH SETTINGS
# ======================
with tab3:
    st.header("🔑 Google Drive OAuth Settings")
    st.markdown("Configure custom OAuth credentials for better API quotas and performance.")
    
    # Get current OAuth configuration
    oauth_config = api.get_google_drive_oauth_config() or {}
    has_custom_oauth = oauth_config.get("has_custom_oauth", False)
    current_client_id = oauth_config.get("client_id", "")
    
    # Current status
    if has_custom_oauth:
        st.success("✅ Custom OAuth credentials are configured")
        st.info(f"**Client ID:** `{current_client_id}`")
        st.info("**Client Secret:** `***` (hidden for security)")
    else:
        st.warning("⚠️ No custom OAuth credentials configured")
        st.info("Using default rclone OAuth (shared quotas). Configure custom credentials for better performance.")
    
    st.markdown("---")
    
    # OAuth configuration form
    with st.form("oauth_config_form"):
        st.subheader("🔧 Configure OAuth Credentials")
        
        st.markdown("""
        **To get your OAuth credentials:**
        1. Go to [Google Cloud Console](https://console.developers.google.com/)
        2. Create a new project or select existing
        3. Enable Google Drive API
        4. Configure OAuth consent screen (choose "Internal" for Google Workspace)
        5. Add scopes: `drive`, `drive.metadata.readonly`, `docs`
        6. Create OAuth client ID as "Desktop app" type
        7. Copy the Client ID and Client Secret below
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            client_id = st.text_input(
                "Client ID",
                value=current_client_id if has_custom_oauth else "",
                placeholder="123456789-abcdef.apps.googleusercontent.com",
                help="Your Google OAuth Client ID"
            )
        
        with col2:
            client_secret = st.text_input(
                "Client Secret",
                type="password",
                placeholder="GOCSPX-abcdef123456",
                help="Your Google OAuth Client Secret"
            )
        
        # Form submission
        col1, col2, col3 = st.columns([1, 1, 2])
        
        with col1:
            save_oauth = st.form_submit_button("💾 Save OAuth Credentials", type="primary")
        
        with col2:
            clear_oauth = st.form_submit_button("🗑️ Clear OAuth Credentials", type="secondary")
        
        if save_oauth:
            if client_id and client_secret:
                with st.spinner("Saving OAuth credentials..."):
                    result = api.save_google_drive_oauth_config(client_id, client_secret)
                    
                    if result and result.get("success"):
                        st.success("✅ OAuth credentials saved successfully!")
                        st.info("🔄 **Restart required:** Please restart MasCloner services for changes to take effect.")
                        st.code("sudo systemctl restart mascloner-api mascloner-scheduler")
                        st.rerun()
                    else:
                        error_msg = result.get("message", "Unknown error") if result else "API error"
                        st.error(f"❌ Failed to save OAuth credentials: {error_msg}")
            else:
                st.error("❌ Both Client ID and Client Secret are required")
        
        if clear_oauth:
            with st.spinner("Clearing OAuth credentials..."):
                # Clear by setting empty values
                result = api.save_google_drive_oauth_config("", "")
                
                if result and result.get("success"):
                    st.success("✅ OAuth credentials cleared!")
                    st.info("🔄 **Restart required:** Please restart MasCloner services for changes to take effect.")
                    st.code("sudo systemctl restart mascloner-api mascloner-scheduler")
                    st.rerun()
                else:
                    error_msg = result.get("message", "Unknown error") if result else "API error"
                    st.error(f"❌ Failed to clear OAuth credentials: {error_msg}")
    
    st.markdown("---")
    
    # Benefits and usage
    with st.expander("ℹ️ About Custom OAuth", expanded=True):
        st.markdown("""
        **Benefits of Custom OAuth:**
        - 🎯 **Dedicated API quotas** (not shared with other rclone users)
        - 📈 **Better performance** for high-usage scenarios
        - 🎛️ **Full control** over quota management and monitoring
        - 🔒 **Enhanced security** with your own credentials
        
        **How it works:**
        1. Your credentials are encrypted and stored securely
        2. MasCloner automatically uses them for all Google Drive operations
        3. The UI will show the correct `rclone authorize` commands with your credentials
        4. You get better API quotas and performance
        
        **Security:**
        - Credentials are encrypted using Fernet encryption
        - Stored in the `.env` file with restricted permissions (600)
        - Never logged or exposed in plain text
        """)
    
    # Test current configuration
    if has_custom_oauth:
        st.markdown("---")
        st.subheader("🧪 Test Current Configuration")
        
        if st.button("🔍 Test OAuth Configuration", use_container_width=True):
            with st.spinner("Testing OAuth configuration..."):
                # Test by trying to get OAuth config
                test_result = api.get_google_drive_oauth_config()
                if test_result and test_result.get("has_custom_oauth"):
                    st.success("✅ OAuth configuration is valid and active")
                    st.info("Your custom OAuth credentials are properly configured and will be used for all Google Drive operations.")
                else:
                    st.error("❌ OAuth configuration test failed")
                    st.warning("The credentials may not be properly loaded. Try restarting the services.")

# ======================
# TAB 4: SYSTEM SETTINGS
# ======================
with tab4:
    st.header("🛠️ System Management")
    
    # Database management
    st.subheader("🗄️ Database Management")
    
    db_info = api.get_database_info()
    if db_info:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total Runs", db_info.get("total_runs", 0))
        
        with col2:
            st.metric("Total Events", db_info.get("total_events", 0))
        
        with col3:
            db_size = db_info.get("database_size", "Unknown")
            st.metric("Database Size", db_size)
    
    st.markdown("---")
    
    # Database cleanup
    with st.form("cleanup_form"):
        st.subheader("🧹 Database Cleanup")
        
        keep_runs = st.number_input(
            "Runs to Keep",
            min_value=10,
            max_value=1000,
            value=100,
            help="Number of recent sync runs to keep (older runs will be deleted)"
        )
        
        cleanup_submitted = st.form_submit_button("🗑️ Clean Database", type="secondary")
        
        if cleanup_submitted:
            with st.spinner("Cleaning database..."):
                result = api.cleanup_database(keep_runs=keep_runs)
                
                if result and result.get("success"):
                    deleted_count = result.get("data", {}).get("deleted_count", 0)
                    st.success(f"✅ Cleaned up {deleted_count} old records!")
                    st.rerun()
                else:
                    st.error("❌ Failed to clean database")
    
    st.markdown("---")
    
    # Database reset
    st.subheader("⚠️ Database Reset")
    st.warning("**DANGER ZONE**: This will permanently delete ALL sync runs and file events!")
    
    with st.expander("🗑️ Reset All Data", expanded=False):
        st.markdown("""
        **What this does:**
        - Deletes ALL sync run records
        - Deletes ALL file event records  
        - Clears the file tree completely
        - Resets all sync history
        
        **What this does NOT affect:**
        - Configuration settings (Google Drive, Nextcloud, sync paths)
        - rclone remote configurations
        - Log files
        - Application settings
        """)
        
        # Show current data counts
        if db_info:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Runs to Delete", db_info.get("total_runs", 0))
            with col2:
                st.metric("Events to Delete", db_info.get("total_events", 0))
        
        # Confirmation steps
        st.markdown("**To proceed, you must confirm both steps:**")
        
        col1, col2 = st.columns(2)
        
        with col1:
            confirm_1 = st.checkbox("✅ I understand this will delete ALL sync data")
        
        with col2:
            confirm_2 = st.checkbox("✅ I want to start completely fresh")
        
        if confirm_1 and confirm_2:
            if st.button("🚨 RESET ALL DATA", type="secondary", use_container_width=True):
                with st.spinner("Resetting database..."):
                    result = api.reset_database()
                    
                    if result and result.get("success"):
                        data = result.get("data", {})
                        runs_deleted = data.get("runs_deleted", 0)
                        events_deleted = data.get("events_deleted", 0)
                        total_deleted = data.get("total_deleted", 0)
                        
                        st.success(f"✅ Database reset successfully!")
                        st.info(f"**Deleted:** {runs_deleted} runs, {events_deleted} events ({total_deleted} total records)")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("❌ Failed to reset database")
        else:
            st.info("Please confirm both checkboxes to enable reset button")
    
    st.markdown("---")
    
    # System information
    st.subheader("ℹ️ System Information")
    
    with st.expander("🔧 API Configuration"):
        config = api.get_config()
        if config:
            # Sanitize config (remove sensitive data)
            display_config = {k: v for k, v in config.items() if "pass" not in k.lower() and "secret" not in k.lower()}
            st.json(display_config)
        else:
            st.error("Failed to load configuration")
    
    with st.expander("📊 System Status Details"):
        if status:
            st.json(status)
        else:
            st.error("Failed to load system status")
    
    # Configuration export
    st.markdown("---")
    st.subheader("📋 Configuration Export")
    
    if st.button("📄 Download Configuration Backup", use_container_width=True):
        config = api.get_config()
        if config:
            # Sanitized config (no passwords)
            sanitized_config = {k: v for k, v in config.items() if "pass" not in k.lower()}
            
            st.download_button(
                label="💾 Download mascloner-config.json",
                data=json.dumps(sanitized_config, indent=2),
                file_name=f"mascloner-config-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True
            )
        else:
            st.error("Failed to get configuration for export")

# Help section
st.markdown("---")

with st.expander("❓ Help & Tips"):
    st.markdown("""
    **Settings Overview:**
    
    - **Schedule Tab**: Configure when syncs run and control the scheduler
    - **Remote Testing Tab**: Test connections to Google Drive and Nextcloud
    - **System Tab**: Manage database, view system info, and export config
    
    **Quick Actions:**
    - Use "Trigger Sync Now" to run a manual sync
    - Test connections after any configuration changes
    - Export configuration regularly as backup
    
    **Troubleshooting:**
    - If remotes show as disconnected, use the Setup Wizard to reconfigure
    - Check system status details for error information
    - Database cleanup can help with performance if you have many old runs
    """)

st.markdown("---")
st.markdown("💡 **Tip**: Use the Setup Wizard if you need to reconfigure Google Drive or Nextcloud connections.")
