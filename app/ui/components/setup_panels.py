"""Reusable panels for the setup wizard UI."""

from __future__ import annotations

from typing import Dict

import streamlit as st


def render_configuration_checklist(config_status: Dict[str, bool]) -> None:
    """Show current configuration status cards."""
    st.subheader("📋 Configuration Status")
    col1, col2, col3 = st.columns(3)

    with col1:
        if config_status["google_drive"]:
            st.success("✅ **Google Drive**\nConfigured and ready")
        else:
            st.error("❌ **Google Drive**\nNeeds configuration")

    with col2:
        if config_status["nextcloud"]:
            st.success("✅ **Nextcloud**\nConfigured and ready")
        else:
            st.error("❌ **Nextcloud**\nNeeds configuration")

    with col3:
        if config_status["sync_config"]:
            st.success("✅ **Sync Paths**\nConfigured and ready")
        else:
            st.error("❌ **Sync Paths**\nNeeds configuration")


def render_fully_configured_view(api, config_status: Dict[str, bool]) -> None:
    """Render management panels when everything is configured."""
    st.success("🎉 **MasCloner is fully configured and ready to use!**")
    st.markdown("All components are properly set up. You can:")

    # Google Drive status
    st.subheader("📋 Current Configuration")
    with st.expander("📱 Google Drive Configuration", expanded=True):
        gdrive_status = api.get_google_drive_status()
        st.success("✅ Google Drive is configured and connected")

        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Remote Name**: {gdrive_status.get('remote_name', 'gdrive')}")
            st.info(f"**Scope**: {gdrive_status.get('scope', 'Unknown')}")

        with col2:
            if gdrive_status.get("folders"):
                st.info(f"**Accessible Folders**: {len(gdrive_status['folders'])} found")
                st.write("**Sample folders:**")
                for folder in gdrive_status["folders"][:5]:
                    st.write(f"📁 {folder}")

    # Nextcloud status
    with st.expander("☁️ Nextcloud Configuration", expanded=True):
        st.success("✅ Nextcloud is configured and connected")
        col1, col2 = st.columns([3, 1])
        with col1:
            st.info("**Status**: Connected via WebDAV")
        with col2:
            if st.button("🧪 Test Connection"):
                with st.spinner("Testing Nextcloud..."):
                    result = api.test_nextcloud("ncwebdav")
                    if result and result.get("success"):
                        st.success("✅ Connection OK")
                    else:
                        st.error("❌ Connection failed")

    # Sync configuration
    with st.expander("🔄 Sync Configuration", expanded=True):
        sync_config = api.get_config()
        st.success("✅ Sync paths are configured")
        col1, col2 = st.columns(2)
        with col1:
            st.info(
                f"**Source**: {sync_config.get('gdrive_remote', 'gdrive')}:"
                f"{sync_config.get('gdrive_src', 'Unknown')}"
            )
        with col2:
            st.info(
                f"**Destination**: {sync_config.get('nc_remote', 'ncwebdav')}:"
                f"{sync_config.get('nc_dest_path', 'Unknown')}"
            )

    st.markdown("---")

    # Management options
    st.subheader("🛠️ Configuration Management")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔄 Go to Home Dashboard", type="primary", use_container_width=True):
            st.switch_page("Home.py")
    with col2:
        if st.button("⚙️ Modify Settings", use_container_width=True):
            st.switch_page("pages/2_Settings.py")
    with col3:
        if st.button("🗑️ Reset All Configuration", type="secondary", use_container_width=True):
            st.session_state.show_reset_options = True
            st.rerun()

    # Fresh start options
    st.markdown("---")
    st.subheader("🔄 Fresh Start Options")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Reset Sync Data Only", use_container_width=True):
            st.session_state.show_data_reset = True
            st.rerun()
    with col2:
        if st.button("🗑️ Reset Everything", type="secondary", use_container_width=True):
            st.session_state.show_full_reset = True
            st.rerun()

    # Reset configuration panel
    if st.session_state.get("show_reset_options", False):
        st.markdown("---")
        st.warning("⚠️ **Reset Configuration**")
        st.markdown("This will remove all current configurations and allow you to start fresh.")
        with st.expander("🔧 Reset Options", expanded=True):
            reset_gdrive = st.checkbox("🗑️ Remove Google Drive configuration")
            reset_nextcloud = st.checkbox("🗑️ Remove Nextcloud configuration")
            reset_sync = st.checkbox("🗑️ Clear sync path configuration")

            if reset_gdrive or reset_nextcloud or reset_sync:
                st.error("**Warning**: This action cannot be undone!")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Confirm Reset", type="secondary", use_container_width=True):
                        with st.spinner("Resetting configuration..."):
                            reset_success = True

                            if reset_gdrive:
                                result = api.remove_google_drive_config()
                                if not (result and result.get("success")):
                                    st.error("Failed to remove Google Drive config")
                                    reset_success = False

                            if reset_nextcloud:
                                current_config = api.get_config() or {}
                                nc_remote_name = current_config.get("nc_remote") or "ncwebdav"
                                result = api.remove_remote(nc_remote_name)
                                if not (result and result.get("success")):
                                    st.error("Failed to remove Nextcloud remote. Please verify in rclone config.")
                                    reset_success = False

                            if reset_sync:
                                clear_config = {
                                    "gdrive_remote": "",
                                    "gdrive_src": "",
                                    "nc_remote": "",
                                    "nc_dest_path": "",
                                }
                                result = api.update_config(clear_config)
                                if not (result and result.get("success")):
                                    st.error("Failed to clear sync configuration")
                                    reset_success = False

                            if reset_success:
                                st.success("✅ Configuration reset successfully!")
                                st.info("🔄 Refreshing wizard...")
                                st.session_state.show_reset_options = False
                                st.rerun()

                with col2:
                    if st.button("❌ Cancel Reset", use_container_width=True):
                        st.session_state.show_reset_options = False
                        st.rerun()

    # Reset sync data
    if st.session_state.get("show_data_reset", False):
        st.markdown("---")
        st.warning("⚠️ **Reset Sync Data Only**")
        st.markdown("This will clear all sync runs and file events but keep your configuration.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Confirm Data Reset", type="secondary", use_container_width=True):
                with st.spinner("Resetting sync data..."):
                    result = api.reset_database()
                    if result and result.get("success"):
                        data = result.get("data", {})
                        st.success(f"✅ Reset {data.get('total_deleted', 0)} records!")
                        st.session_state.show_data_reset = False
                        st.rerun()
                    else:
                        st.error("❌ Failed to reset data")
        with col2:
            if st.button("❌ Cancel", use_container_width=True):
                st.session_state.show_data_reset = False
                st.rerun()

    # Full reset panel
    if st.session_state.get("show_full_reset", False):
        st.markdown("---")
        st.error("🚨 **Reset Everything**")
        st.markdown(
            "This will clear ALL data AND reset all configurations. "
            "You'll need to set up everything again."
        )

        confirm_full = st.checkbox("✅ I understand this will delete everything and I'll need to reconfigure")
        if confirm_full:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚨 CONFIRM FULL RESET", type="secondary", use_container_width=True):
                    with st.spinner("Resetting everything..."):
                        db_result = api.reset_database()
                        current_config = api.get_config() or {}
                        nc_remote_name = current_config.get("nc_remote") or "ncwebdav"
                        gdrive_result = api.remove_google_drive_config()
                        nextcloud_result = api.remove_remote(nc_remote_name)
                        clear_config = {
                            "gdrive_remote": "",
                            "gdrive_src": "",
                            "nc_remote": "",
                            "nc_dest_path": "",
                        }
                        config_result = api.update_config(clear_config)

                        operations_ok = (
                            db_result and db_result.get("success")
                            and gdrive_result and gdrive_result.get("success")
                            and config_result and config_result.get("success")
                            and (nextcloud_result and nextcloud_result.get("success"))
                        )

                        if operations_ok:
                            st.success("✅ Full reset completed!")
                            st.info("🔄 Please refresh the page to start the setup wizard")
                            st.session_state.show_full_reset = False
                            st.rerun()
                        else:
                            issues = []
                            if not (db_result and db_result.get("success")):
                                issues.append("database reset")
                            if not (gdrive_result and gdrive_result.get("success")):
                                issues.append("Google Drive removal")
                            if not (nextcloud_result and nextcloud_result.get("success")):
                                issues.append("Nextcloud remote removal")
                            if not (config_result and config_result.get("success")):
                                issues.append("config update")
                            detail = ", ".join(issues) if issues else "unknown error"
                            st.error(f"❌ Reset failed ({detail})")
            with col2:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.show_full_reset = False
                    st.rerun()
        else:
            st.info("Please confirm to enable reset button")
