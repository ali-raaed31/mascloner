"""
MasCloner Setup Wizard Page

Smart guided setup flow that checks existing configurations.
"""

import streamlit as st
from typing import Dict, Any, Optional, List
import json
import logging
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
logger = logging.getLogger(__name__)


def _ensure_folder_state(key: str) -> Dict[str, Any]:
    """Initialize and return folder picker state from session."""
    if key not in st.session_state:
        st.session_state[key] = {
            "top_level": [],
            "children": {},
            "selected_top": "",
            "selected_child": "",
            "selected_path": ""
        }
    return st.session_state[key]


def open_folder_modal(remote_name: str, state_key: str, label: str) -> None:
    """Open modal for folder browsing."""
    st.session_state["folder_modal"] = {
        "open": True,
        "remote": remote_name,
        "state_key": state_key,
        "label": label
    }


def close_folder_modal():
    """Close folder modal."""
    st.session_state.setdefault("folder_modal", {})["open"] = False


def get_tree_state(state_key: str, remote_name: str) -> Dict[str, Any]:
    """Get or initialize tree state for a folder picker."""
    tree_states = st.session_state.setdefault("folder_tree_states", {})
    state = tree_states.get(state_key)
    if not state or state.get("remote") != remote_name:
        state = {
            "remote": remote_name,
            "nodes": {},
            "expanded": set(),
            "selected_temp": "",
            "last_error": None
        }
        tree_states[state_key] = state
    return state


def _sanitize_path(path: str) -> str:
    return path.replace("/", "_slash_").replace(" ", "_space_")


def load_children_for_path(remote_name: str, state_key: str, path: str) -> List[str]:
    """Load child folders for a specific path into tree state."""
    tree_state = get_tree_state(state_key, remote_name)
    try:
        response = api.browse_folders(remote_name, path=path)
        if response and (response.get("success") or response.get("status") == "success"):
            children = sorted(response.get("folders", []))
            tree_state["nodes"][path] = {
                "children": children,
                "fetched": True
            }
            logger.info(
                "UI: modal loaded %d children for remote=%s path='%s'",
                len(children),
                remote_name,
                path or "/"
            )
            return children
        else:
            tree_state["nodes"][path] = {
                "children": [],
                "fetched": True
            }
            tree_state["last_error"] = response
            logger.warning(
                "UI: modal failed to load children for remote=%s path='%s' response=%s",
                remote_name,
                path or "/",
                response
            )
            return []
    except Exception as exc:
        tree_state["nodes"][path] = {
            "children": [],
            "fetched": True
        }
        tree_state["last_error"] = str(exc)
        logger.exception(
            "UI: modal encountered error loading children remote=%s path='%s'",
            remote_name,
            path or "/"
        )
        return []


def ensure_children_loaded(remote_name: str, state_key: str, path: str) -> List[str]:
    tree_state = get_tree_state(state_key, remote_name)
    node = tree_state["nodes"].get(path)
    if not node or not node.get("fetched"):
        return load_children_for_path(remote_name, state_key, path)
    return node["children"]


def set_modal_style():
    if not st.session_state.get("_modal_style_injected"):
        st.markdown(
            """
            <style>
            .mc-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(10, 13, 23, 0.72);
                z-index: 1000;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .mc-modal-box {
                width: min(92vw, 720px);
                max-height: 85vh;
                background: #0f172a;
                border-radius: 18px;
                padding: 24px;
                box-shadow: 0 24px 60px rgba(15, 23, 42, 0.45);
                border: 1px solid rgba(148, 163, 184, 0.18);
                display: flex;
                flex-direction: column;
            }
            .mc-modal-scroll {
                margin-top: 16px;
                padding: 8px 12px;
                border-radius: 12px;
                border: 1px solid rgba(148, 163, 184, 0.18);
                background: rgba(15, 23, 42, 0.6);
                overflow-y: auto;
                flex: 1;
            }
            .mc-modal-row {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 4px 0;
            }
            .mc-modal-selected {
                margin-top: 12px;
                font-size: 0.9rem;
                color: rgba(226, 232, 240, 0.85);
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        st.session_state["_modal_style_injected"] = True


def render_tree_nodes(remote_name: str, state_key: str, path: str, level: int = 0):
    tree_state = get_tree_state(state_key, remote_name)
    children = ensure_children_loaded(remote_name, state_key, path)
    if not children:
        if path and tree_state.get("last_error"):
            st.warning(f"Could not load subfolders for `{path}`")
        return
    
    indent_symbol = "\u2003" * level  # em space for indentation
    
    for child in children:
        child_path = f"{path}/{child}".strip("/")
        child_key = _sanitize_path(child_path or child)
        child_node = tree_state["nodes"].get(child_path, {"children": [], "fetched": False})
        expanded = child_path in tree_state["expanded"]
        has_children = bool(child_node.get("children")) if child_node.get("fetched") else True
        
        cols = st.columns([0.12, 0.68, 0.2], gap="small")
        toggle_label = f"{indent_symbol}{'▾' if expanded else '▸'}"
        select_label = f"{indent_symbol}{'📂' if expanded else '📁'} {child}"
        
        with cols[0]:
            if st.button(
                toggle_label,
                key=f"{state_key}_toggle_{child_key}",
                disabled=not has_children
            ):
                if expanded:
                    tree_state["expanded"].discard(child_path)
                else:
                    tree_state["expanded"].add(child_path)
                    ensure_children_loaded(remote_name, state_key, child_path)
        
        with cols[1]:
            if st.button(
                select_label,
                key=f"{state_key}_select_{child_key}"
            ):
                tree_state["selected_temp"] = child_path
        
        with cols[2]:
            if child_path == tree_state.get("selected_temp"):
                st.success("Selected", icon="✅")
            elif not has_children and child_node.get("fetched"):
                st.caption("Empty")
            else:
                st.write("")
        
        if expanded:
            render_tree_nodes(remote_name, state_key, child_path, level + 1)


def render_folder_modal():
    modal = st.session_state.get("folder_modal")
    if not modal or not modal.get("open"):
        return
    
    remote_name = modal["remote"]
    state_key = modal["state_key"]
    label = modal["label"]
    
    tree_state = get_tree_state(state_key, remote_name)
    picker_state = _ensure_folder_state(state_key)
    if not tree_state.get("selected_temp"):
        tree_state["selected_temp"] = picker_state.get("selected_path", "")
    
    ensure_children_loaded(remote_name, state_key, "")
    set_modal_style()
    
    st.markdown("<div class='mc-modal-overlay'>", unsafe_allow_html=True)
    modal_container = st.container()
    with modal_container:
        st.markdown("<div class='mc-modal-box'>", unsafe_allow_html=True)
        st.subheader(f"{label} Folder Explorer")
        st.caption("Click ▸ to expand folders. Select a folder, then confirm.")
        
        st.markdown("<div class='mc-modal-scroll'>", unsafe_allow_html=True)
        render_tree_nodes(remote_name, state_key, "")
        st.markdown("</div>", unsafe_allow_html=True)
        
        current = tree_state.get("selected_temp", "")
        st.markdown(
            f"<div class='mc-modal-selected'>Current selection: "
            f"{'`' + current + '`' if current else 'None selected'}</div>",
            unsafe_allow_html=True
        )
        
        col1, col2, col3 = st.columns([0.3, 0.35, 0.35])
        with col1:
            if st.button("Close", key=f"{state_key}_modal_close"):
                close_folder_modal()
                st.experimental_rerun()
        with col2:
            if st.button("Clear selection", key=f"{state_key}_modal_clear"):
                tree_state["selected_temp"] = ""
                picker_state["selected_path"] = ""
                manual_key = f"{state_key}_manual"
                st.session_state[manual_key] = ""
        with col3:
            if st.button(
                "Use folder",
                key=f"{state_key}_modal_use",
                type="primary",
                disabled=not current
            ):
                picker_state["selected_path"] = current
                manual_key = f"{state_key}_manual"
                st.session_state[manual_key] = current
                close_folder_modal()
                st.experimental_rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_remote_folder_picker(
    remote_label: str,
    remote_name: str,
    state_key: str,
    placeholder: str
) -> str:
    """Render folder picker with modal tree explorer and manual override."""
    state = _ensure_folder_state(state_key)
    manual_key = f"{state_key}_manual"
    st.session_state.setdefault(manual_key, state["selected_path"])
    
    col_path, col_browse, col_clear = st.columns([0.65, 0.23, 0.12])
    with col_path:
        selected_value = st.text_input(
            f"{remote_label} path",
            key=manual_key,
            placeholder=placeholder
        ).strip()
    with col_browse:
        st.button(
            f"🌲 Browse {remote_label}",
            key=f"{state_key}_open_modal",
            use_container_width=True,
            on_click=open_folder_modal,
            args=(remote_name, state_key, remote_label)
        )
    with col_clear:
        def _clear_selection():
            st.session_state[manual_key] = ""
            tree_state = st.session_state.get("folder_tree_states", {}).get(state_key)
            if tree_state:
                tree_state["selected_temp"] = ""
        st.button(
            "Clear",
            key=f"{state_key}_clear",
            use_container_width=True,
            on_click=_clear_selection
        )
    selected_value = st.session_state.get(manual_key, "").strip()
    state["selected_path"] = selected_value
    if selected_value:
        st.caption(f"Selected {remote_label} path: `{selected_value}`")
    return state["selected_path"]

st.title("🧙‍♂️ MasCloner Setup Wizard")

notice = st.session_state.pop("setup_wizard_notice", None)
if notice:
    st.success(notice)

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

# If everything is already configured, show status and reset option
if config_status["all_configured"]:
    st.success("🎉 **MasCloner is fully configured and ready to use!**")
    st.markdown("All components are properly set up. You can:")
    
    # Show current configuration
    st.subheader("📋 Current Configuration")
    
    # Google Drive status
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
        
        # Test connection
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
            st.info(f"**Source**: {sync_config.get('gdrive_remote', 'gdrive')}:{sync_config.get('gdrive_src', 'Unknown')}")
        with col2:
            st.info(f"**Destination**: {sync_config.get('nc_remote', 'ncwebdav')}:{sync_config.get('nc_dest_path', 'Unknown')}")
    
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
    
    # Quick database reset option
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
    
    # Reset confirmation
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
                                # Clear sync configuration
                                clear_config = {
                                    "gdrive_remote": "",
                                    "gdrive_src": "",
                                    "nc_remote": "",
                                    "nc_dest_path": ""
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
    
    # Data reset confirmation
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
    
    # Full reset confirmation
    if st.session_state.get("show_full_reset", False):
        st.markdown("---")
        st.error("🚨 **Reset Everything**")
        st.markdown("This will clear ALL data AND reset all configurations. You'll need to set up everything again.")
        
        confirm_full = st.checkbox("✅ I understand this will delete everything and I'll need to reconfigure")
        
        if confirm_full:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚨 CONFIRM FULL RESET", type="secondary", use_container_width=True):
                    with st.spinner("Resetting everything..."):
                        # Reset database first
                        db_result = api.reset_database()
                        
                        # Capture current configuration for remote names before clearing
                        current_config = api.get_config() or {}
                        nc_remote_name = current_config.get("nc_remote") or "ncwebdav"
                        
                        # Reset Google Drive config
                        gdrive_result = api.remove_google_drive_config()
                        
                        # Remove Nextcloud remote
                        nextcloud_result = api.remove_remote(nc_remote_name)
                        
                        # Clear sync configuration
                        clear_config = {
                            "gdrive_remote": "",
                            "gdrive_src": "",
                            "nc_remote": "",
                            "nc_dest_path": ""
                        }
                        config_result = api.update_config(clear_config)
                        
                        operations_ok = (
                            db_result and db_result.get("success") and
                            gdrive_result and gdrive_result.get("success") and
                            config_result and config_result.get("success") and
                            (nextcloud_result and nextcloud_result.get("success"))
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

else:
    # Show setup wizard for missing configurations
    st.markdown("**Let's get MasCloner configured for your environment!**")
    
    # Configuration checklist
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
    
    st.markdown("---")
    
    # Setup steps state management
    if "setup_step" not in st.session_state:
        # Determine starting step based on what's already configured
        if not config_status["google_drive"]:
            st.session_state.setup_step = 1  # Start with Google Drive
        elif not config_status["nextcloud"]:
            st.session_state.setup_step = 2  # Start with Nextcloud
        elif not config_status["sync_config"]:
            st.session_state.setup_step = 3  # Start with sync paths
        else:
            st.session_state.setup_step = 4  # Final step
    else:
        # Auto-advance when a step has been completed
        if st.session_state.setup_step == 1 and config_status["google_drive"]:
            st.session_state.setup_step = 2
        if st.session_state.setup_step == 2 and config_status["nextcloud"]:
            st.session_state.setup_step = 3
        if st.session_state.setup_step == 3 and config_status["sync_config"]:
            st.session_state.setup_step = 4
    
    if "setup_data" not in st.session_state:
        st.session_state.setup_data = {}
    
    # Progress calculation (only count steps that need to be done)
    total_steps = sum([
        1 if not config_status["google_drive"] else 0,
        1 if not config_status["nextcloud"] else 0, 
        1 if not config_status["sync_config"] else 0,
        1  # Final step
    ])
    
    current_step = 0
    if config_status["google_drive"]:
        current_step += 1
    if config_status["nextcloud"]:
        current_step += 1
    if config_status["sync_config"]:
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
        
        # Get available folders for selection
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📱 Google Drive Source")
            selected_folder = render_remote_folder_picker(
                remote_label="Google Drive",
                remote_name=gdrive_remote_name,
                state_key="gdrive_folder_picker",
                placeholder="Shared drives/MyTeam/Documents"
            )
        
        with col2:
            st.subheader("☁️ Nextcloud Destination")
            dest_folder = render_remote_folder_picker(
                remote_label="Nextcloud",
                remote_name=nextcloud_remote_name,
                state_key="nextcloud_folder_picker",
                placeholder="Backups/GoogleDrive"
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

render_folder_modal()

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
