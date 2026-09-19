"""
MasCloner API Client for Streamlit UI

Handles communication with the FastAPI backend with optional authentication support.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

ContractModel = TypeVar("ContractModel", bound=BaseModel)


class APIActionResult(BaseModel):
    """Outcome returned by an API operation that changes durable state."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ScheduleSettingsContract(BaseModel):
    """Canonical schedule response consumed by Streamlit pages."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    interval_min: int
    jitter_sec: int
    interval: str
    next_run_time: Optional[str] = None


class ScheduleUpdateContract(BaseModel):
    """Canonical payload accepted by ``POST /schedule``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    interval_min: int
    jitter_sec: int


class RclonePerformanceContract(BaseModel):
    """Canonical rclone performance representation used for GET and POST."""

    model_config = ConfigDict(extra="forbid")

    transfers: int
    checkers: int
    tpslimit: int
    tpslimit_burst: int
    buffer_size: Optional[str] = None
    drive_chunk_size: Optional[str] = None
    drive_upload_cutoff: Optional[str] = None
    fast_list: bool


class RunContract(BaseModel):
    """Canonical terminal run shape returned by ``GET /runs``."""

    model_config = ConfigDict(extra="forbid")

    id: int
    status: str
    started_at: str
    finished_at: Optional[str] = None
    num_added: int
    num_updated: int
    bytes_transferred: int
    errors: int
    log_path: Optional[str] = None
    message: Optional[str] = None

    @property
    def mutation_count(self) -> int:
        """Return the number of files added or updated by this run."""
        return self.num_added + self.num_updated

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate terminal duration from the canonical timestamps."""
        if not self.finished_at:
            return None
        try:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
            return max(0.0, (finished - started).total_seconds())
        except ValueError:
            return None


class CurrentRunContract(BaseModel):
    """Canonical live-run shape returned by ``GET /runs/current``."""

    model_config = ConfigDict(extra="forbid")

    id: int
    status: str
    started_at: str
    num_added: int
    num_updated: int
    bytes_transferred: int
    errors: int
    log_path: Optional[str] = None
    is_process_running: bool
    percentage: Optional[float] = None
    speed_bps: Optional[float] = None
    recent_events: Optional[list[Dict[str, Any]]] = None

    @property
    def mutation_count(self) -> int:
        """Return transfers reported by the current sync snapshot."""
        return self.num_added + self.num_updated

    @property
    def elapsed_seconds(self) -> Optional[float]:
        """Calculate elapsed time from the canonical live-run start timestamp."""
        try:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())
        except ValueError:
            return None


class EndpointStatusContract(BaseModel):
    """Secret-free durable endpoint status used by connection cards."""

    model_config = ConfigDict(extra="forbid")

    configured: bool
    remote_name: Optional[str] = None
    scope: Optional[str] = None
    folders: Optional[list[str]] = None
    last_test: Optional[str] = None
    url: Optional[str] = None
    user: Optional[str] = None
    vendor: Optional[str] = None


class SyncRouteSideContract(BaseModel):
    """Verification outcome for one configured route side."""

    model_config = ConfigDict(extra="forbid")

    remote_ok: bool
    path_ok: bool
    message: str


class SyncRouteVerificationContract(BaseModel):
    """Secret-free verification result for the persisted SyncRoute."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    source: SyncRouteSideContract
    destination: SyncRouteSideContract


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

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Extract FastAPI's useful validation detail without exposing response internals."""
        try:
            detail = response.json().get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list):
                return "; ".join(
                    str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                    for item in detail
                )
        except ValueError:
            pass
        return response.text or f"API error: {response.status_code}"

    def _make_request(self, method: str, endpoint: str, **kwargs: Any) -> Optional[Any]:
        """Make HTTP request to API."""
        try:
            with httpx.Client(timeout=self.timeout, auth=self._auth) as client:
                response = client.request(method, f"{self.base_url}{endpoint}", **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            message = self._error_message(e.response)
            if e.response.status_code == 401:
                logger.warning("API authentication failed: Invalid credentials")
            else:
                logger.error("API HTTP error: %s %s", e.response.status_code, message)
            return {"success": False, "message": message}
        except httpx.RequestError as e:
            logger.error("API request failed: %s", e)
            return {"success": False, "message": f"Connection error: {e}"}
        except Exception as e:
            logger.error("Unexpected API error: %s", e)
            return {"success": False, "message": f"Unexpected API error: {e}"}

    @staticmethod
    def _parse_contract(
        model: type[ContractModel], payload: Any, endpoint: str
    ) -> Optional[ContractModel]:
        """Validate a successful response at the UI boundary."""
        if not isinstance(payload, dict):
            return None
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            logger.error("Invalid %s response: %s", endpoint, exc)
            return None

    @staticmethod
    def _parse_action(payload: Any) -> APIActionResult:
        """Convert success and non-2xx API responses into one page-friendly result."""
        if not isinstance(payload, dict):
            return APIActionResult(success=False, message="The API returned no response")
        try:
            return APIActionResult.model_validate(payload)
        except ValidationError:
            return APIActionResult(
                success=False,
                message=str(payload.get("message", "The API returned an invalid response")),
            )

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

    def get_schedule_settings(self) -> Optional[ScheduleSettingsContract]:
        """Get the canonical schedule contract for UI pages."""
        return self._parse_contract(
            ScheduleSettingsContract, self.get_schedule(), "/schedule"
        )

    def update_schedule(self, schedule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update sync schedule."""
        return self._make_request("POST", "/schedule", json=schedule)

    def save_schedule(self, settings: ScheduleUpdateContract) -> APIActionResult:
        """Persist a validated schedule payload and retain validation feedback."""
        return self._parse_action(
            self.update_schedule(settings.model_dump())
        )

    def start_scheduler(self) -> Optional[Dict[str, Any]]:
        """Start the scheduler."""
        return self._make_request("POST", "/schedule/start")

    def stop_scheduler(self) -> Optional[Dict[str, Any]]:
        """Stop the scheduler."""
        return self._make_request("POST", "/schedule/stop")

    def set_schedule_paused(self, paused: bool) -> APIActionResult:
        """Pause or resume the durable scheduler through one page-level operation."""
        response = self.stop_scheduler() if paused else self.start_scheduler()
        return self._parse_action(response)

    def get_runs(
        self, limit: int = 50, status: Optional[str] = None
    ) -> Optional[Any]:
        """Get sync runs, optionally filtered by status."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        return self._make_request("GET", "/runs", params=params)

    def get_recent_runs(
        self, limit: int = 50, status: Optional[str] = None
    ) -> Optional[list[RunContract]]:
        """Get canonical run records from the list-shaped runs response."""
        response = self.get_runs(limit=limit, status=status)
        if not isinstance(response, list):
            return None
        try:
            return [RunContract.model_validate(run) for run in response]
        except ValidationError as exc:
            logger.error("Invalid /runs response: %s", exc)
            return None

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

    def get_google_drive_endpoint_status(self) -> Optional[EndpointStatusContract]:
        """Get the canonical, secret-free Google Drive configuration status."""
        return self._parse_contract(
            EndpointStatusContract,
            self.get_google_drive_status(),
            "/oauth/google-drive/status",
        )

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

    def get_nextcloud_endpoint_status(self) -> Optional[EndpointStatusContract]:
        """Get the canonical, secret-free Nextcloud configuration status."""
        return self._parse_contract(
            EndpointStatusContract,
            self.get_nextcloud_status(),
            "/test/nextcloud/status",
        )

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

    def get_rclone_performance(self) -> Optional[RclonePerformanceContract]:
        """Get the canonical rclone performance contract for UI pages."""
        return self._parse_contract(
            RclonePerformanceContract, self.get_rclone_config(), "/rclone/config"
        )

    def update_rclone_config(self, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update rclone performance configuration."""
        return self._make_request("POST", "/rclone/config", json=settings)

    def save_rclone_performance(
        self, settings: RclonePerformanceContract
    ) -> APIActionResult:
        """Persist a complete validated rclone performance payload."""
        return self._parse_action(
            self.update_rclone_config(settings.model_dump())
        )

    # Live sync monitoring
    def get_current_run(self) -> Optional[Dict[str, Any]]:
        """Get the currently running sync, if any.

        Returns:
            Run information dict or None if no sync is running
        """
        return self._make_request("GET", "/runs/current")

    def get_current_run_snapshot(self) -> Optional[CurrentRunContract]:
        """Get a validated active-run snapshot, or ``None`` when the engine is idle."""
        return self._parse_contract(
            CurrentRunContract, self.get_current_run(), "/runs/current"
        )

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

    def verify_sync_route(self) -> Optional[SyncRouteVerificationContract]:
        """Probe the persisted source and destination paths without exposing secrets."""
        return self._parse_contract(
            SyncRouteVerificationContract,
            self._make_request("POST", "/config/paths/verify"),
            "/config/paths/verify",
        )
