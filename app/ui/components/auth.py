"""Authentication component for MasCloner Streamlit UI.

Provides a login form when authentication is required by the API.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import streamlit as st


def is_auth_required() -> bool:
    """Check if UI authentication is enabled via environment variable."""
    return os.getenv("MASCLONER_AUTH_ENABLED", "0").lower() in ("1", "true", "yes", "on")


def get_stored_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Get credentials from session state if available."""
    username = st.session_state.get("auth_username")
    password = st.session_state.get("auth_password")
    return username, password


def store_credentials(username: str, password: str) -> None:
    """Store credentials in session state."""
    st.session_state.auth_username = username
    st.session_state.auth_password = password
    st.session_state.auth_authenticated = True


def clear_credentials() -> None:
    """Clear stored credentials from session state."""
    st.session_state.pop("auth_username", None)
    st.session_state.pop("auth_password", None)
    st.session_state.auth_authenticated = False


def is_authenticated() -> bool:
    """Check if user is authenticated."""
    if not is_auth_required():
        return True
    return st.session_state.get("auth_authenticated", False)


def render_login_form(api_client) -> bool:
    """Render login form and return True if authentication succeeds.

    Args:
        api_client: APIClient instance to verify credentials

    Returns:
        True if authenticated, False otherwise
    """
    if not is_auth_required():
        return True

    # Check if already authenticated
    if is_authenticated():
        return True

    # Try credentials from environment first
    env_username = os.getenv("MASCLONER_AUTH_USERNAME")
    env_password = os.getenv("MASCLONER_AUTH_PASSWORD")

    if env_username and env_password:
        api_client.set_auth(env_username, env_password)
        success, message = api_client.check_auth()
        if success:
            store_credentials(env_username, env_password)
            return True

    st.title("🔐 MasCloner Login")
    st.markdown("Authentication is required to access MasCloner.")

    with st.form("login_form"):
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

        if submitted:
            if not username or not password:
                st.error("Please enter both username and password.")
                return False

            # Try to authenticate
            api_client.set_auth(username, password)
            success, message = api_client.check_auth()

            if success:
                store_credentials(username, password)
                st.success("✅ Login successful!")
                st.rerun()
            else:
                st.error(f"❌ Login failed: {message}")
                api_client.clear_auth()
                return False

    return False


def render_logout_button() -> None:
    """Render logout button in sidebar."""
    if not is_auth_required():
        return

    if is_authenticated():
        username = st.session_state.get("auth_username", "User")
        st.sidebar.markdown(f"**Logged in as:** {username}")
        if st.sidebar.button("🚪 Logout", use_container_width=True):
            clear_credentials()
            st.rerun()


def require_auth(api_client) -> bool:
    """Require authentication for the page.

    Call this at the top of each page that requires authentication.

    Args:
        api_client: APIClient instance

    Returns:
        True if authenticated and should continue, False if login form shown
    """
    if not is_auth_required():
        return True

    # Check session state for existing auth
    username, password = get_stored_credentials()
    if username and password:
        api_client.set_auth(username, password)
        success, _ = api_client.check_auth()
        if success:
            return True
        # Credentials expired or invalid, clear them
        clear_credentials()

    # Show login form
    if render_login_form(api_client):
        return True

    st.stop()
    return False

