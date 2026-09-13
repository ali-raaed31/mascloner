"""Side-effect-free EndpointInspector implementation (ADR 0005)."""

from __future__ import annotations

import asyncio
import configparser
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Dict, List, Optional, Union

from ..configuration.models import GoogleDriveSourceDraft, NextcloudDestinationDraft
from ..configuration.stores import redact_secrets
from .exceptions import (
    InspectionAuthError,
    InspectionError,
    InspectionNetworkError,
    InspectionTimeoutError,
    InspectionValidationError,
    UnsupportedEndpointError,
)
from .models import (
    BrowseResult,
    ConnectionTestResult,
    EndpointConcept,
    EndpointStatusResult,
    FolderEntry,
    SizeEstimationResult,
)

logger = logging.getLogger(__name__)

SUPPORTED_REMOTES = {EndpointConcept.SOURCE.value, EndpointConcept.DESTINATION.value}


def _classify_error(error_text: str) -> str:
    """Classify error string into domain categories."""
    lower = error_text.lower()
    if any(k in lower for k in ["401", "unauthorized", "invalid_grant", "access_denied", "token expired", "auth"]):
        return "auth_failure"
    if any(k in lower for k in ["timeout", "timed out", "deadline exceeded"]):
        return "timeout"
    if any(k in lower for k in ["connection refused", "no route to host", "name or service not known", "network", "unreachable"]):
        return "network_failure"
    return "unknown"


class EndpointInspector:
    """Side-effect-free inspector for GoogleDriveSource and NextcloudDestination."""

    def __init__(
        self,
        rclone_conf_path: Optional[Path] = None,
        rclone_bin: Optional[Path | str] = None,
        default_timeout: float = 15.0,
        max_browse_entries: int = 100,
    ) -> None:
        if rclone_conf_path:
            self._rclone_conf = Path(rclone_conf_path)
        else:
            from ..api.config import config
            base = config.get_base_config()
            self._rclone_conf = base["base_dir"] / base["rclone_conf"]

        self._rclone_bin = str(rclone_bin or os.environ.get("RCLONE_BIN") or "rclone")
        self._default_timeout = default_timeout
        self._max_browse_entries = max_browse_entries

    def _validate_endpoint(self, endpoint: Union[str, EndpointConcept]) -> str:
        remote = endpoint.value if isinstance(endpoint, EndpointConcept) else str(endpoint).strip()
        if remote not in SUPPORTED_REMOTES:
            raise UnsupportedEndpointError(
                f"Unsupported endpoint {remote!r}. Only fixed endpoints "
                f"{sorted(SUPPORTED_REMOTES)} are supported."
            )
        return remote

    def _validate_path(self, path: str) -> str:
        clean = path.strip().strip("/")
        if ".." in clean.split("/"):
            raise InspectionValidationError(f"Invalid path {path!r}: traversal not permitted")
        return clean

    async def _run_rclone(
        self,
        args: List[str],
        config_path: Path,
        timeout: Optional[float] = None,
        secrets: Optional[List[Optional[str]]] = None,
    ) -> tuple[int, str, str]:
        """Execute rclone subprocess safely and asynchronously with bounded timeouts and redaction."""
        effective_timeout = timeout or self._default_timeout
        cmd = [self._rclone_bin, "--config", str(config_path)] + args

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(), timeout=effective_timeout
            )
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise InspectionTimeoutError(f"Inspection timed out after {effective_timeout}s")
        except asyncio.CancelledError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise

        if secrets:
            stdout = redact_secrets(stdout, secrets)
            stderr = redact_secrets(stderr, secrets)

        return process.returncode or 0, stdout, stderr

    # --- Connection testing ---

    async def test_connection(
        self, endpoint: Union[str, EndpointConcept], timeout: Optional[float] = None
    ) -> ConnectionTestResult:
        """Test connection against managed endpoint without modifying live state."""
        remote = self._validate_endpoint(endpoint)
        start_time = time.monotonic()

        if not self._rclone_conf.exists():
            return ConnectionTestResult(
                success=False,
                endpoint=remote,
                message="rclone.conf does not exist",
                error_category="unconfigured",
            )

        cmd_args = ["lsd", f"{remote}:", "--max-depth=1"] if remote == "ncwebdav" else ["about", f"{remote}:"]

        try:
            retcode, stdout, stderr = await self._run_rclone(
                cmd_args, self._rclone_conf, timeout=timeout
            )
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            if retcode == 0:
                return ConnectionTestResult(
                    success=True,
                    endpoint=remote,
                    message=f"Connection to {remote} successful",
                    duration_ms=duration_ms,
                )

            err_msg = stderr.strip() or stdout.strip() or f"exit code {retcode}"
            category = _classify_error(err_msg)
            return ConnectionTestResult(
                success=False,
                endpoint=remote,
                message=f"Connection failed: {err_msg}",
                duration_ms=duration_ms,
                error_category=category,
            )
        except InspectionTimeoutError as exc:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            return ConnectionTestResult(
                success=False,
                endpoint=remote,
                message=str(exc),
                duration_ms=duration_ms,
                error_category="timeout",
            )
        except Exception as exc:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            return ConnectionTestResult(
                success=False,
                endpoint=remote,
                message=f"Connection error: {exc}",
                duration_ms=duration_ms,
                error_category="unknown",
            )

    async def test_source_draft(
        self, draft: GoogleDriveSourceDraft, timeout: Optional[float] = None
    ) -> ConnectionTestResult:
        """Test Google Drive candidate draft in an isolated sandbox config."""
        start_time = time.monotonic()
        secrets = [draft.token, draft.client_secret, draft.client_id]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_conf = Path(tmpdir) / "rclone.conf"
            cp = configparser.RawConfigParser(interpolation=None)
            cp.optionxform = str
            cp.add_section("gdrive")
            cp.set("gdrive", "type", "drive")
            cp.set("gdrive", "scope", draft.scope)
            cp.set("gdrive", "token", draft.token)
            if draft.client_id:
                cp.set("gdrive", "client_id", draft.client_id)
            if draft.client_secret:
                cp.set("gdrive", "client_secret", draft.client_secret)
            if draft.team_drive:
                cp.set("gdrive", "team_drive", draft.team_drive)

            with open(tmp_conf, "w", encoding="utf-8") as f:
                cp.write(f)
            os.chmod(tmp_conf, 0o600)

            try:
                retcode, stdout, stderr = await self._run_rclone(
                    ["about", "gdrive:"], tmp_conf, timeout=timeout, secrets=secrets
                )
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                if retcode == 0:
                    return ConnectionTestResult(
                        success=True,
                        endpoint="gdrive",
                        message="Google Drive draft connection successful",
                        duration_ms=duration_ms,
                    )
                err_msg = stderr.strip() or stdout.strip() or f"exit code {retcode}"
                return ConnectionTestResult(
                    success=False,
                    endpoint="gdrive",
                    message=f"Connection test failed: {err_msg}",
                    duration_ms=duration_ms,
                    error_category=_classify_error(err_msg),
                )
            except InspectionTimeoutError as exc:
                return ConnectionTestResult(
                    success=False,
                    endpoint="gdrive",
                    message=str(exc),
                    duration_ms=round((time.monotonic() - start_time) * 1000, 2),
                    error_category="timeout",
                )
            except Exception as exc:
                return ConnectionTestResult(
                    success=False,
                    endpoint="gdrive",
                    message=f"Connection test error: {exc}",
                    duration_ms=round((time.monotonic() - start_time) * 1000, 2),
                    error_category="unknown",
                )

    async def test_destination_draft(
        self, draft: NextcloudDestinationDraft, timeout: Optional[float] = None
    ) -> ConnectionTestResult:
        """Test Nextcloud candidate draft in an isolated sandbox config."""
        start_time = time.monotonic()
        secrets = [draft.password, draft.user]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_conf = Path(tmpdir) / "rclone.conf"
            # Create remote in temp config
            create_args = [
                "config",
                "create",
                "ncwebdav",
                "webdav",
                f"url={draft.url}",
                f"vendor={draft.vendor}",
                f"user={draft.user}",
                f"pass={draft.password}",
            ]
            try:
                retcode, stdout, stderr = await self._run_rclone(
                    create_args, tmp_conf, timeout=timeout, secrets=secrets
                )
                if retcode != 0:
                    err_msg = stderr.strip() or stdout.strip() or f"exit code {retcode}"
                    return ConnectionTestResult(
                        success=False,
                        endpoint="ncwebdav",
                        message=f"Failed to create draft remote: {err_msg}",
                        duration_ms=round((time.monotonic() - start_time) * 1000, 2),
                        error_category=_classify_error(err_msg),
                    )

                os.chmod(tmp_conf, 0o600)
                # Test connection via lsd
                test_ret, test_out, test_err = await self._run_rclone(
                    ["lsd", "ncwebdav:", "--max-depth=1"], tmp_conf, timeout=timeout, secrets=secrets
                )
                duration_ms = round((time.monotonic() - start_time) * 1000, 2)
                if test_ret == 0:
                    return ConnectionTestResult(
                        success=True,
                        endpoint="ncwebdav",
                        message="Nextcloud draft connection successful",
                        duration_ms=duration_ms,
                    )
                err_msg = test_err.strip() or test_out.strip() or f"exit code {test_ret}"
                return ConnectionTestResult(
                    success=False,
                    endpoint="ncwebdav",
                    message=f"Connection test failed: {err_msg}",
                    duration_ms=duration_ms,
                    error_category=_classify_error(err_msg),
                )
            except InspectionTimeoutError as exc:
                return ConnectionTestResult(
                    success=False,
                    endpoint="ncwebdav",
                    message=str(exc),
                    duration_ms=round((time.monotonic() - start_time) * 1000, 2),
                    error_category="timeout",
                )
            except Exception as exc:
                return ConnectionTestResult(
                    success=False,
                    endpoint="ncwebdav",
                    message=f"Connection test error: {exc}",
                    duration_ms=round((time.monotonic() - start_time) * 1000, 2),
                    error_category="unknown",
                )

    # --- Directory browsing ---

    async def browse_folders(
        self,
        endpoint: Union[str, EndpointConcept],
        path: str = "",
        limit: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> BrowseResult:
        """Browse directories at the given endpoint path without mutating configuration."""
        remote = self._validate_endpoint(endpoint)
        clean_path = self._validate_path(path)
        max_count = limit or self._max_browse_entries
        start_time = time.monotonic()

        target = f"{remote}:{clean_path}" if clean_path else f"{remote}:"
        args = ["lsd", target, "--max-depth=1"]

        try:
            retcode, stdout, stderr = await self._run_rclone(args, self._rclone_conf, timeout=timeout)
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            if retcode != 0:
                err_msg = stderr.strip() or stdout.strip() or f"exit code {retcode}"
                return BrowseResult(
                    success=False,
                    endpoint=remote,
                    path=clean_path,
                    error=f"Browse failed: {err_msg}",
                    duration_ms=duration_ms,
                )

            # Parse lines from rclone lsd output
            folders: List[str] = []
            entries: List[FolderEntry] = []
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    folder_name = " ".join(parts[4:])
                    full_p = f"{clean_path}/{folder_name}" if clean_path else folder_name
                    folders.append(full_p)
                    entries.append(FolderEntry(name=folder_name, path=full_p, is_dir=True))

            total_count = len(folders)
            truncated = False
            if total_count > max_count:
                folders = folders[:max_count]
                entries = entries[:max_count]
                truncated = True

            return BrowseResult(
                success=True,
                endpoint=remote,
                path=clean_path,
                folders=folders,
                entries=entries,
                truncated=truncated,
                total_count=total_count,
                duration_ms=duration_ms,
            )
        except InspectionTimeoutError as exc:
            return BrowseResult(
                success=False,
                endpoint=remote,
                path=clean_path,
                error=str(exc),
                duration_ms=round((time.monotonic() - start_time) * 1000, 2),
            )
        except Exception as exc:
            return BrowseResult(
                success=False,
                endpoint=remote,
                path=clean_path,
                error=f"Browse error: {exc}",
                duration_ms=round((time.monotonic() - start_time) * 1000, 2),
            )

    # --- Status inspection ---

    async def get_source_status(self, include_preview_folders: bool = True) -> EndpointStatusResult:
        """Inspect status of GoogleDriveSource safely."""
        from ..configuration import Configuration
        from ..api.db import get_db_session

        cfg = Configuration(session_factory=get_db_session)
        meta = cfg.get_endpoint_metadata("gdrive")
        if not meta or meta.details.get("type") != "drive" or meta.details.get("token_configured") != "true":
            return EndpointStatusResult(
                configured=False,
                endpoint="gdrive",
                remote_name="gdrive",
            )

        scope = meta.details.get("scope")
        folders: Optional[List[str]] = None
        if include_preview_folders:
            browse_res = await self.browse_folders("gdrive", path="", limit=10)
            if browse_res.success:
                folders = browse_res.folders

        return EndpointStatusResult(
            configured=True,
            endpoint="gdrive",
            remote_name="gdrive",
            scope=scope,
            folders=folders,
            details={k: v for k, v in meta.details.items() if not k.endswith("_token") and k != "token"},
        )

    async def get_destination_status(self, include_preview_folders: bool = False) -> EndpointStatusResult:
        """Inspect status of NextcloudDestination safely."""
        from ..configuration import Configuration
        from ..api.db import get_db_session

        cfg = Configuration(session_factory=get_db_session)
        nc_info = cfg.get_nextcloud_metadata()
        if not nc_info or not nc_info.get("configured"):
            return EndpointStatusResult(
                configured=False,
                endpoint="ncwebdav",
                remote_name="ncwebdav",
            )

        folders: Optional[List[str]] = None
        if include_preview_folders:
            browse_res = await self.browse_folders("ncwebdav", path="", limit=10)
            if browse_res.success:
                folders = browse_res.folders

        return EndpointStatusResult(
            configured=True,
            endpoint="ncwebdav",
            remote_name="ncwebdav",
            url=nc_info.get("url"),
            user=nc_info.get("user"),
            folders=folders,
            details=nc_info,
        )

    # --- Size estimation ---

    async def estimate_size(
        self, source_path: str = "", dest_path: str = "", timeout: Optional[float] = 60.0
    ) -> SizeEstimationResult:
        """Estimate volume and file count for source without touching destination."""
        start_time = time.monotonic()
        clean_src = self._validate_path(source_path)
        target = f"gdrive:{clean_src}" if clean_src else "gdrive:"

        try:
            retcode, stdout, stderr = await self._run_rclone(
                ["size", target, "--json"], self._rclone_conf, timeout=timeout
            )
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            if retcode != 0:
                err_msg = stderr.strip() or stdout.strip() or f"exit code {retcode}"
                return SizeEstimationResult(
                    success=False,
                    error=f"Size estimation failed: {err_msg}",
                    duration_ms=duration_ms,
                )

            data = json.loads(stdout)
            size_bytes = data.get("bytes", 0)
            file_count = data.get("count", 0)

            return SizeEstimationResult(
                success=True,
                size_mb=round(size_bytes / 1024 / 1024, 2),
                file_count=file_count,
                folder_count=0,
                duration_ms=duration_ms,
            )
        except InspectionTimeoutError as exc:
            return SizeEstimationResult(
                success=False,
                error=str(exc),
                duration_ms=round((time.monotonic() - start_time) * 1000, 2),
            )
        except Exception as exc:
            return SizeEstimationResult(
                success=False,
                error=f"Size estimation error: {exc}",
                duration_ms=round((time.monotonic() - start_time) * 1000, 2),
            )
