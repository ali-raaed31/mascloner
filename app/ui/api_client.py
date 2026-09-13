"""
MasCloner API Client for Streamlit UI

Handles communication with the FastAPI backend with optional authentication support.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class APIClient:
    """Client for communicating with MasCloner API.

    Supports HTTP Basic Auth when credentials are provided.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        auth: Optional[Tuple[str, str]] = None,
    ):
        """Initialize API client.

        Args:
            base_url: API base URL
            auth: Optional tuple of (username, password) for Basic Auth
        """
        self.base_url = base_url
        self.timeout = 30.0
        self._auth = auth

        # Try to load auth from environment if not provided
        if self._auth is None:
            username = os.getenv("MASCLONER_AUTH_USERNAME")
            password = os.getenv("MASCLONER_AUTH_PASSWORD")
            if username and password:
                self._auth = (username, password)

    def set_auth(self, username: str, password: str) -> None:
        """Set authentication credentials."""
        self._auth = (username, password)

    def clear_auth(self) -> None:
        """Clear authentication credentials."""
        self._auth = None

    def _make_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Make HTTP request to API."""
        try:
            with httpx.Client(timeout=self.timeout, auth=self._auth) as client:
                response = client.request(method, f"{self.base_url}{endpoint}", **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.warning("API authentication failed: Invalid credentials")
            else:
                logger.error("API HTTP error: %s %s", e.response.status_code, e.response.text)
            return None
        except httpx.RequestError as e:
            logger.error("API request failed: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected API error: %s", e)
            return None

    def check_auth(self) -> Tuple[bool, str]:
        """Check if authentication is working.

        Returns:
            Tuple of (success, message)
        """
        try:
            with httpx.Client(timeout=self.timeout, auth=self._auth) as client:
                response = client.get(f"{self.base_url}/status")
                if response.status_code == 200:
                    return True, "Authenticated successfully"
                elif response.status_code == 401:
                    return False, "Invalid credentials"
                else:
                    return False, f"API error: {response.status_code}"
        except httpx.RequestError as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"

    def get_health(self) -> Optional[Dict[str, Any]]:
        """Get API health status (no auth required)."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/health")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return None

    def get_status(self) -> Optional[Dict[str, Any]]:
        """Get system status."""
        return self._make_request("GET", "/status")

    def get_config(self) -> Optional[Dict[str, Any]]:
        """Get current configuration."""
        return self._make_request("GET", "/config")

    def update_config(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update configuration."""
        return self._make_request("POST", "/config", json=config)

    def get_schedule(self) -> Optional[Dict[str, Any]]:
        """Get sync schedule."""
        return self._make_request("GET", "/schedule")

    def update_schedule(self, schedule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update sync schedule."""
        return self._make_request("POST", "/schedule", json=schedule)

    def start_scheduler(self) -> Optional[Dict[str, Any]]:
        """Start the scheduler."""
        return self._make_request("POST", "/schedule/start")

    def stop_scheduler(self) -> Optional[Dict[str, Any]]:
        """Stop the scheduler."""
        return self._make_request("POST", "/schedule/stop")

    def get_runs(
        self, limit: int = 50, status: Optional[str] = None
    ) -> Optional[Any]:
        """Get sync runs, optionally filtered by status."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        return self._make_request("GET", "/runs", params=params)

    def trigger_sync(self) -> Optional[Dict[str, Any]]:
        """Trigger manual sync."""
        return self._make_request("POST", "/runs")

    def get_run_events(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Get events for a specific run."""
        return self._make_request("GET", f"/runs/{run_id}/events")

    def get_events(self, limit: int = 200) -> Optional[Dict[str, Any]]:
        """Get recent file events."""
        return self._make_request("GET", f"/events?limit={limit}")

    def test_google_drive_connection(self) -> Optional[Dict[str, Any]]:
        """Test Google Drive connection."""
        return self._make_request("POST", "/oauth/google-drive/test")

    def test_gdrive(self, remote_name: str = "gdrive") -> Optional[Dict[str, Any]]:
        """Test Google Drive connection (backward-compatible alias)."""
        return self.test_google_drive_connection()

    def test_nextcloud(self, remote_name: str = "ncwebdav") -> Optional[Dict[str, Any]]:
        """Test Nextcloud connection."""
        return self._make_request("POST", "/test/nextcloud", json={"remote_name": remote_name})

    def test_nextcloud_webdav(
        self, url: str, user: str, password: str, remote_name: str = "ncwebdav"
    ) -> Optional[Dict[str, Any]]:
        """Test Nextcloud WebDAV connection and create remote."""
        return self._make_request(
            "POST",
            "/test/nextcloud/webdav",
            json={"url": url, "user": user, "pass": password, "remote_name": remote_name},
        )

    def browse_folders(self, remote_name: str, path: str = "") -> Optional[Dict[str, Any]]:
        """Browse folders in a remote."""
        params = {"path": path} if path else {}
        return self._make_request("GET", f"/browse/folders/{remote_name}", params=params)

    def estimate_size(self, source: str, dest: str) -> Optional[Dict[str, Any]]:
        """Estimate sync size."""
        params = {"source": source, "dest": dest}
        return self._make_request("GET", "/estimate/size", params=params)

    def cleanup_database(self, keep_runs: int = 100) -> Optional[Dict[str, Any]]:
        """Clean up old runs."""
        params = {"keep_runs": keep_runs}
        return self._make_request("POST", "/maintenance/cleanup", params=params)

    def reset_database(self) -> Optional[Dict[str, Any]]:
        """Reset database (delete all runs and events)."""
        return self._make_request("POST", "/maintenance/reset")

    def get_database_info(self) -> Optional[Dict[str, Any]]:
        """Get database information."""
        return self._make_request("GET", "/database/info")

    def get_retention_status(self) -> Optional[Dict[str, Any]]:
        """Get current retention policy configuration and last run report."""
        return self._make_request("GET", "/maintenance/retention")

    def trigger_retention(
        self, dry_run: bool = False, retention_days: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Execute a 60-day history retention pass."""
        params = {"dry_run": dry_run, "retention_days": retention_days}
        return self._make_request("POST", "/maintenance/retention", params=params)

    def trigger_retention_cleanup(
        self, dry_run: bool = False, retention_days: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Execute a 60-day history retention pass (alias)."""
        return self.trigger_retention(dry_run=dry_run, retention_days=retention_days)

    def create_backup_bundle(self) -> Optional[Dict[str, Any]]:
        """Trigger an online, consistency-verified SQLite database backup."""
        return self._make_request("POST", "/maintenance/backup")

    def test_oauth_credentials(
        self, client_id: str, client_secret: str
    ) -> Optional[Dict[str, Any]]:
        """Test Google Drive OAuth custom client credentials."""
        return self._make_request(
            "POST",
            "/oauth/google-drive/oauth-config/test",
            json={"client_id": client_id, "client_secret": client_secret},
        )

    def get_google_drive_oauth_config(self) -> Optional[Dict[str, Any]]:
        """Get Google Drive OAuth client configuration."""
        return self._make_request("GET", "/oauth/google-drive/oauth-config")

    def get_gdrive_oauth_config(self) -> Optional[Dict[str, Any]]:
        """Get Google Drive OAuth client configuration (backward-compatible alias)."""
        return self.get_google_drive_oauth_config()

    def save_google_drive_oauth_config(
        self, client_id: str, client_secret: str
    ) -> Optional[Dict[str, Any]]:
        """Save Google Drive custom OAuth client credentials."""
        return self._make_request(
            "POST",
            "/oauth/google-drive/oauth-config",
            json={"client_id": client_id, "client_secret": client_secret},
        )

    def save_gdrive_oauth_config(
        self, client_id: str, client_secret: str
    ) -> Optional[Dict[str, Any]]:
        """Save Google Drive custom OAuth client credentials (backward-compatible alias)."""
        return self.save_google_drive_oauth_config(client_id, client_secret)

    def configure_google_drive_oauth(
        self,
        token: str,
        scope: str = "drive.readonly",
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Configure Google Drive with OAuth token."""
        data = {"token": token, "scope": scope}
        if client_id:
            data["client_id"] = client_id
        if client_secret:
            data["client_secret"] = client_secret
        return self._make_request("POST", "/oauth/google-drive", json=data)

    def configure_gdrive_oauth(
        self,
        token: str,
        scope: str = "drive.readonly",
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Configure Google Drive with OAuth token (backward-compatible alias)."""
        return self.configure_google_drive_oauth(
            token=token, scope=scope, client_id=client_id, client_secret=client_secret
        )

    def get_google_drive_status(self) -> Optional[Dict[str, Any]]:
        """Get Google Drive configuration status."""
        return self._make_request("GET", "/oauth/google-drive/status")

    def get_gdrive_status(self) -> Optional[Dict[str, Any]]:
        """Get Google Drive configuration status (backward-compatible alias)."""
        return self.get_google_drive_status()

    def remove_google_drive_config(self) -> Optional[Dict[str, Any]]:
        """Remove Google Drive configuration."""
        return self._make_request("DELETE", "/oauth/google-drive")

    def remove_gdrive_config(self) -> Optional[Dict[str, Any]]:
        """Remove Google Drive configuration (backward-compatible alias)."""
        return self.remove_google_drive_config()

    def get_nextcloud_status(self) -> Optional[Dict[str, Any]]:
        """Get Nextcloud destination configuration status."""
        return self._make_request("GET", "/test/nextcloud/status")

    def remove_nextcloud_config(self) -> Optional[Dict[str, Any]]:
        """Remove Nextcloud configuration."""
        return self._make_request("DELETE", "/test/nextcloud")

    def remove_remote(self, remote_name: str) -> Optional[Dict[str, Any]]:
        """Remove an rclone remote."""
        if remote_name == "gdrive":
            return self.remove_google_drive_config()
        elif remote_name == "ncwebdav":
            return self.remove_nextcloud_config()
        return self._make_request("DELETE", f"/remotes/{remote_name}")

    def validate_config(self) -> Optional[Dict[str, Any]]:
        """Validate configuration."""
        return self._make_request("GET", "/config/validate")

    # Rclone performance tuning
    def get_rclone_config(self) -> Optional[Dict[str, Any]]:
        """Get current rclone performance configuration."""
        return self._make_request("GET", "/rclone/config")

    def update_rclone_config(self, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update rclone performance configuration."""
        return self._make_request("POST", "/rclone/config", json=settings)

    # Live sync monitoring
    def get_current_run(self) -> Optional[Dict[str, Any]]:
        """Get the currently running sync, if any.

        Returns:
            Run information dict or None if no sync is running
        """
        return self._make_request("GET", "/runs/current")

    def get_run_logs(
        self, run_id: int, since: int = 0, limit: int = 100
    ) -> Optional[Dict[str, Any]]:
        """Get log lines for a sync run.

        Args:
            run_id: The run ID to get logs for
            since: Line number to start from (for incremental polling)
            limit: Maximum number of lines to return

        Returns:
            Dict with logs list, next_line for pagination, and is_live flag
        """
        return self._make_request(
            "GET", f"/runs/{run_id}/logs", params={"since": since, "limit": limit}
        )

    def stop_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Request graceful stop of a running sync.

        Sends SIGTERM to rclone, which finishes the current file before stopping.

        Args:
            run_id: The run ID to stop

        Returns:
            Success response or None on error
        """
        return self._make_request("POST", f"/runs/{run_id}/stop")

    def get_sync_paths(self) -> Optional[Dict[str, Any]]:
        """Get current sync folder paths."""
        return self._make_request("GET", "/config/paths")

    def update_sync_paths(self, paths: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update sync folder paths."""
        return self._make_request("POST", "/config/paths", json=paths)
