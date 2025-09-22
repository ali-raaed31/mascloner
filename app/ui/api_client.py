"""
MasCloner API Client for Streamlit UI

Handles communication with the FastAPI backend.
"""

import httpx
import json
from typing import Dict, Any, Optional
from datetime import datetime


class APIClient:
    """Client for communicating with MasCloner API."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8787"):
        self.base_url = base_url
        self.timeout = 30.0
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Make HTTP request to API."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, f"{self.base_url}{endpoint}", **kwargs)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"API request failed: {e}")
            return None
    
    def get_health(self) -> Optional[Dict[str, Any]]:
        """Get API health status."""
        return self._make_request("GET", "/health")
    
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
    
    def get_runs(self, limit: int = 50) -> Optional[Dict[str, Any]]:
        """Get sync runs."""
        return self._make_request("GET", f"/runs?limit={limit}")
    
    def trigger_sync(self) -> Optional[Dict[str, Any]]:
        """Trigger manual sync."""
        return self._make_request("POST", "/runs")
    
    def get_run_events(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Get events for a specific run."""
        return self._make_request("GET", f"/runs/{run_id}/events")
    
    def get_events(self, limit: int = 200) -> Optional[Dict[str, Any]]:
        """Get recent file events."""
        return self._make_request("GET", f"/events?limit={limit}")
    
    def get_tree(self, path: str = "") -> Optional[Dict[str, Any]]:
        """Get file tree structure."""
        params = {"path": path} if path else {}
        return self._make_request("GET", "/tree", params=params)
    
    def get_tree_status(self, path: str) -> Optional[Dict[str, Any]]:
        """Get status for specific path."""
        return self._make_request("GET", f"/tree/status/{path}")
    
    def test_gdrive(self, remote_name: str) -> Optional[Dict[str, Any]]:
        """Test Google Drive connection."""
        return self._make_request("POST", "/test/gdrive", json={"remote_name": remote_name})
    
    def test_nextcloud(self, remote_name: str) -> Optional[Dict[str, Any]]:
        """Test Nextcloud connection."""
        return self._make_request("POST", "/test/nextcloud", json={"remote_name": remote_name})
    
    def test_nextcloud_webdav(self, url: str, user: str, password: str, remote_name: str) -> Optional[Dict[str, Any]]:
        """Test Nextcloud WebDAV connection and create remote."""
        return self._make_request("POST", "/test/nextcloud/webdav", json={
            "url": url,
            "user": user,
            "pass": password,
            "remote_name": remote_name
        })
    
    def browse_folders(self, remote_name: str, path: str = "") -> Optional[Dict[str, Any]]:
        """Browse folders in a remote."""
        params = {"path": path} if path else {}
        return self._make_request("GET", f"/browse/folders/{remote_name}", params=params)
    
    def estimate_size(self, source: str, dest: str) -> Optional[Dict[str, Any]]:
        """Estimate sync operation size."""
        return self._make_request("GET", "/estimate/size", params={"source": source, "dest": dest})
    
    def cleanup_database(self, days: int = 30) -> Optional[Dict[str, Any]]:
        """Clean up old database records."""
        return self._make_request("POST", f"/maintenance/cleanup?days={days}")
    
    def get_database_info(self) -> Optional[Dict[str, Any]]:
        """Get database information."""
        return self._make_request("GET", "/database/info")
