"""MasCloner Streamlit Web UI.

Main entry point and declarative navigation router for the console.
"""

from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

# Ensure repository root and UI directory are on sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
ui_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(ui_dir) not in sys.path:
    sys.path.insert(0, str(ui_dir))

from app import __version__

try:
    from app.ui.api_client import APIClient
    from app.ui.components.auth import render_logout_button, require_auth
except ImportError:
    from api_client import APIClient
    from components.auth import render_logout_button, require_auth

# Configure Streamlit page
st.set_page_config(
    page_title="MasCloner Console",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": f"MasCloner v{__version__} - Automated Google Drive to Nextcloud sync",
    },
)


@st.cache_resource
def get_api_client():
    return APIClient()


api = get_api_client()

# Enforce centralized authentication boundary
if not require_auth(api):
    st.stop()

# Sidebar Branding & Global Info
st.sidebar.markdown(f"## 🔄 **MasCloner** `v{__version__}`")
render_logout_button()
st.sidebar.divider()

# Declarative Multi-page Navigation
pages = {
    "Operations": [
        st.Page("pages/dashboard.py", title="Live Dashboard", icon="⚡", default=True),
        st.Page("pages/live_monitor.py", title="Live Monitor", icon="📡"),
        st.Page("pages/history.py", title="Run History & Audit", icon="📋"),
    ],
    "Configuration": [
        st.Page("pages/storage.py", title="Storage & Connections", icon="🔗"),
        st.Page("pages/schedule.py", title="Schedule & Engine", icon="⏱️"),
    ],
    "System": [
        st.Page("pages/maintenance.py", title="Retention & Backups", icon="🛡️"),
        st.Page("pages/diagnostics.py", title="Diagnostics", icon="🩺"),
    ],
}

pg = st.navigation(pages)
pg.run()
