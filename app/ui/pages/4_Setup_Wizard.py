"""
MasCloner Configuration Hub

Tabbed experience to manage Google Drive, Nextcloud, and sync path settings.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import APIClient  # noqa: E402
from components.google_drive_setup import GoogleDriveSetup  # noqa: E402

st.set_page_config(page_title="Setup - MasCloner", page_icon="🛠️", layout="wide")

logger = logging.getLogger(__name__)
api = APIClient()

st.title("🛠️ MasCloner Setup & Configuration")


def _rerun() -> None:
    rerun_fn = getattr(st, "experimental_rerun", None) or getattr(st, "rerun", None)
    if rerun_fn:
        rerun_fn()

# --- Helpers -----------------------------------------------------------------


def fetch_remote_folders(remote_name: str, path: str) -> list[str]:
    """Fetch immediate child folders for a remote path."""
    try:
        response = api.browse_folders(remote_name, path=path) if path else api.browse_folders(remote_name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to browse folders remote=%s path='%s': %s", remote_name, path, exc)
        return []

    if not response:
        return []

    if response.get("success") or response.get("status") == "success":
        raw_folders = response.get("folders", []) or []
        return sorted({folder.split("/")[-1] for folder in raw_folders if folder})

    logger.warning(
        "Browse folders returned failure for remote=%s path='%s': %s",
        remote_name,
        path,
        response.get("error") or response.get("message"),
    )
    return []


def render_path_editor(remote_label: str, remote_name: str, state_prefix: str, initial_path: str) -> str:
    """Render a simple folder browser for a remote and return the selected path."""
    path_key = f"{state_prefix}_path"
    selected_key = f"{state_prefix}_child"
    manual_key = f"{state_prefix}_manual"
    reset_flag = f"{state_prefix}_reset_child"

    if path_key not in st.session_state:
        st.session_state[path_key] = initial_path.strip("/") if initial_path else ""
    current_path = st.session_state[path_key]

    # Handle child reset flag before creating the widget
    if st.session_state.get(reset_flag, False):
        st.session_state[selected_key] = ""
        st.session_state[reset_flag] = False

    st.markdown(f"**Current {remote_label} path:** `{current_path or '/'}`")

    folders = fetch_remote_folders(remote_name, current_path)
    if not folders:
        st.info("No subfolders found for this location.")

    st.session_state.setdefault(selected_key, "")
    selected_child = st.selectbox(
        f"{remote_label} subfolders",
        [""] + folders,
        key=selected_key,
    )

    col_open, col_up = st.columns(2)
    with col_open:
        if st.button("📂 Open folder", key=f"{state_prefix}_open", use_container_width=True, disabled=not selected_child):
            new_path = "/".join(filter(None, [current_path, selected_child])).strip("/")
            st.session_state[path_key] = new_path
            st.session_state[manual_key] = new_path
            st.session_state[reset_flag] = True
            _rerun()

    with col_up:
        if st.button("⬆️ Go up", key=f"{state_prefix}_up", use_container_width=True, disabled=not current_path):
            parent = "/".join(current_path.split("/")[:-1]).strip("/")
            st.session_state[path_key] = parent
            st.session_state[manual_key] = parent
            st.session_state[reset_flag] = True
            _rerun()

    st.session_state.setdefault(manual_key, current_path)
    manual_value = st.text_input(
        "Manual path",
        key=manual_key,
        help="Paste a complete relative path if you already know it.",
    ).strip()

    if st.button("✅ Use manual path", key=f"{state_prefix}_apply_manual", use_container_width=True):
        st.session_state[path_key] = manual_value
        st.session_state[reset_flag] = True
        _rerun()

    return st.session_state[path_key]


def render_summary_panel():
    """Display quick summary of current configuration in the sidebar."""
    config = api.get_config() or {}
    status = api.get_status() or {}
    remotes = status.get("remotes_configured", {})

    st.sidebar.markdown("### 🔍 Current Snapshot")
    st.sidebar.markdown(
        f"- **Google Drive remote**: `{config.get('gdrive_remote', 'gdrive')}` "
        f"({'✅' if remotes.get('gdrive') else '❌'})"
    )
    st.sidebar.markdown(
        f"- **Google Drive path**: `{config.get('gdrive_src', 'Not set')}`"
    )
    st.sidebar.markdown(
        f"- **Nextcloud remote**: `{config.get('nc_remote', 'ncwebdav')}` "
        f"({'✅' if remotes.get('nextcloud') else '❌'})"
    )
    st.sidebar.markdown(
        f"- **Nextcloud path**: `{config.get('nc_dest_path', 'Not set')}`"
    )
    st.sidebar.markdown(
        f"- **Scheduler**: `{'Running' if status.get('scheduler_running') else 'Stopped'}`"
    )


def render_google_drive_tab():
    st.subheader("Google Drive Connection")

    gdrive_status = api.get_google_drive_status() or {}
    configured = gdrive_status.get("configured", False)

    if configured and not st.session_state.get("gdrive_reconfigure", False):
        st.success("✅ Google Drive is connected")
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Remote name**: `{gdrive_status.get('remote_name', 'gdrive')}`")
            st.info(f"**Scope**: `{gdrive_status.get('scope', 'drive.readonly')}`")
        with col2:
            if gdrive_status.get("folders"):
                st.write("**Sample folders:**")
                for folder in gdrive_status["folders"][:5]:
                    st.write(f"📁 {folder}")

        st.markdown("---")
        col_actions = st.columns(3)
        with col_actions[0]:
            if st.button("🔄 Reconfigure", key="gdrive_reconfigure_btn", use_container_width=True):
                st.session_state.gdrive_reconfigure = True
                _rerun()
        with col_actions[1]:
            if st.button("🧪 Test connection", key="gdrive_test_btn", use_container_width=True):
                with st.spinner("Testing Google Drive..."):
                    result = api.test_google_drive_connection()
                    if result and result.get("success"):
                        st.success("✅ Connection OK")
                    else:
                        st.error(f"❌ Test failed: {result.get('message', 'Unknown error') if result else 'API error'}")
        with col_actions[2]:
            if st.button("🗑️ Remove remote", key="gdrive_remove_btn", use_container_width=True):
                with st.spinner("Removing Google Drive config..."):
                    result = api.remove_google_drive_config()
                    if result and result.get("success"):
                        st.success("✅ Removed. Please reconfigure.")
                        st.session_state.gdrive_reconfigure = True
                        _rerun()
                    else:
                        st.error("❌ Failed to remove Google Drive configuration")
        return

    st.info("Configure Google Drive access using the simple token flow.")
    gdrive_setup = GoogleDriveSetup(api)
    setup_complete = gdrive_setup.render_setup_instructions()
    if setup_complete:
        st.success("✅ Google Drive configured successfully!")
        st.session_state.pop("gdrive_reconfigure", None)
        _rerun()


def render_nextcloud_tab():
    st.subheader("Nextcloud Connection")

    status = api.get_status() or {}
    remotes = status.get("remotes_configured", {})
    configured = remotes.get("nextcloud", False)
    show_form = st.session_state.get("nextcloud_reconfigure", not configured)

    if configured and not show_form:
        st.success("✅ Nextcloud remote detected")
        if st.button("🔄 Reconfigure Nextcloud", use_container_width=True):
            st.session_state.nextcloud_reconfigure = True
            _rerun()
        return

    st.info("Enter your Nextcloud WebDAV details to (re)create the rclone remote.")
    with st.form("nextcloud_setup_form"):
        col1, col2 = st.columns(2)
        with col1:
            nc_url = st.text_input(
                "Nextcloud WebDAV URL",
                placeholder="https://cloud.example.com/remote.php/dav/files/username/",
            )
            nc_user = st.text_input("Username", placeholder="your_username")
        with col2:
            nc_pass = st.text_input(
                "App Password",
                type="password",
                help="Recommended: use an app-specific password.",
            )
            remote_name = st.text_input(
                "Remote name",
                value="ncwebdav",
                help="Name for the rclone remote that points to Nextcloud.",
            )
        submitted = st.form_submit_button("💾 Test & Save Nextcloud", type="primary")

    if submitted:
        if not (nc_url and nc_user and nc_pass and remote_name):
            st.error("Please fill out all fields.")
            return
        with st.spinner("Testing Nextcloud connection..."):
            result = api.test_nextcloud_webdav(
                url=nc_url,
                user=nc_user,
                password=nc_pass,
                remote_name=remote_name,
            )
        if result and result.get("success"):
            st.success("✅ Nextcloud remote verified and saved!")
            st.session_state.pop("nextcloud_reconfigure", None)
            _rerun()
        else:
            st.error(f"❌ Nextcloud test failed: {result.get('message', 'Unknown error') if result else 'API error'}")


def render_paths_tab():
    st.subheader("Sync Paths")
    config = api.get_config() or {}

    gdrive_remote_name = config.get("gdrive_remote") or "gdrive"
    nextcloud_remote_name = config.get("nc_remote") or "ncwebdav"

    tab_source, tab_dest = st.tabs(["📱 Google Drive", "☁️ Nextcloud"])

    with tab_source:
        selected_source = render_path_editor(
            remote_label="Google Drive",
            remote_name=gdrive_remote_name,
            state_prefix="gdrive",
            initial_path=config.get("gdrive_src", ""),
        )

    with tab_dest:
        selected_dest = render_path_editor(
            remote_label="Nextcloud",
            remote_name=nextcloud_remote_name,
            state_prefix="nextcloud",
            initial_path=config.get("nc_dest_path", ""),
        )

    st.markdown("---")
    st.caption(
        "Only folders inside the configured remotes are listed. "
        "Paste a full path above if you need to target deeper folders."
    )

    if st.button("💾 Save Sync Paths", type="primary", use_container_width=True):
        if not (selected_source and selected_dest):
            st.error("Please choose both a source and destination path.")
            return
        payload = {
            "gdrive_remote": gdrive_remote_name,
            "gdrive_src": selected_source,
            "nc_remote": nextcloud_remote_name,
            "nc_dest_path": selected_dest,
        }
        with st.spinner("Saving sync paths..."):
            result = api.update_config(payload)
        if result and result.get("success"):
            st.success("✅ Sync paths saved!")
        else:
            st.error("❌ Failed to save paths. Please try again.")


# --- Page Layout --------------------------------------------------------------

render_summary_panel()

status = api.get_status()
if not status:
    st.error("❌ Cannot connect to MasCloner API")
    st.stop()

tabs = st.tabs(["📱 Google Drive", "☁️ Nextcloud", "🔄 Sync Paths"])

with tabs[0]:
    render_google_drive_tab()

with tabs[1]:
    render_nextcloud_tab()

with tabs[2]:
    render_paths_tab()

st.markdown("---")
with st.expander("❓ Help & Troubleshooting"):
    st.markdown(
        """
        - **Google Drive not working**: run `rclone authorize "drive"` again and paste the new token.
        - **Nextcloud connection fails**: verify your WebDAV URL and app password.
        - **Folders not loading**: ensure the remote names exist in `rclone.conf`.
        - **Need a fresh start?** Use the settings page to reset configuration or database.
        """
    )
