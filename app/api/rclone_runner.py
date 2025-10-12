"""rclone execution and JSON log parsing for MasCloner."""

import subprocess
import json
import os
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .config import config, get_log_dir, get_rclone_conf_path, resolve_conflict_filename

logger = logging.getLogger(__name__)


@dataclass
class SyncEvent:
    """Individual file sync event."""
    timestamp: datetime
    action: str  # added, updated, skipped, error, conflict
    file_path: str
    file_size: int
    message: str
    file_hash: Optional[str] = None


@dataclass
class SyncResult:
    """Result of a sync operation."""
    status: str  # success, error, partial
    num_added: int = 0
    num_updated: int = 0
    bytes_transferred: int = 0
    errors: int = 0
    events: List[SyncEvent] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.events is None:
            self.events = []


class RcloneLogParser:
    """Parser for rclone JSON log output based on official rclone documentation."""
    
    def __init__(self):
        # Stats pattern for fallback when individual file events aren't available
        self.stats_pattern = re.compile(r'Transferred:\s+(\d+)\s+/\s+(\d+),\s+(\d+)\s+files,\s+(\d+)\s+errors')
    
    # Map rclone log messages to our action types based on official rclone JSON log format
    ACTION_MAP = {
        # Official rclone JSON log message patterns (exact matches)
        "Copied (new)": "added",
        "Copied (replaced)": "updated", 
        "Copied": "added",  # Generic copy
        "Transferred (new)": "added",
        "Transferred (replaced)": "updated",
        "Transferred": "added",
        
        # Skip operations
        "Skipped": "skipped",
        "Skipping": "skipped",
        
        # Error operations
        "Can't copy": "error",
        "Failed to copy": "error",
        "ERROR": "error",
    }
    
    def parse_line(self, line: str) -> Optional[SyncEvent]:
        """Parse a single JSON log line from rclone based on official format."""
        if not line.strip():
            return None
            
        try:
            obj = json.loads(line.strip())
        except (json.JSONDecodeError, AttributeError):
            # Not a JSON line, might be stats or other output
            return None
            
        # Official rclone JSON log format fields
        level = obj.get("level", "").upper()
        msg = obj.get("msg", "")
        file_path = obj.get("object", "")  # Official field name for file path
        file_size = int(obj.get("size", 0))
        timestamp_str = obj.get("time", "")
        
        # Parse timestamp if available
        timestamp = datetime.utcnow()
        if timestamp_str:
            try:
                # Handle rclone's timestamp format: "2024-01-05T12:45:54.986126-05:00"
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                pass  # Use current time if parsing fails
        
        # Debug logging for troubleshooting
        if file_path:  # Only log if there's a file path (actual file operations)
            logger.debug(f"Parsing rclone log: level={level}, msg='{msg}', object='{file_path}', size={file_size}")
        
        # Determine action from message content
        action = None
        
        # Check for error level first
        if level == "ERROR":
            action = "error"
        else:
            # Look for action indicators in message (exact match for official patterns)
            for key, val in self.ACTION_MAP.items():
                if key in msg:  # Exact match for official rclone messages
                    action = val
                    logger.debug(f"Matched action '{key}' -> '{val}' for file: {file_path}")
                    break
        
        # Skip if no recognizable action
        if not action:
            if file_path:  # Only log if there was a file path
                logger.debug(f"No action matched for file: {file_path}, msg: '{msg}'")
            return None
        
        # Check for conflict scenarios
        if "already exists" in msg.lower() or "conflict" in msg.lower():
            action = "conflict"
        
        return SyncEvent(
            timestamp=timestamp,
            action=action,
            file_path=file_path,
            file_size=file_size,
            message=msg,
            file_hash=obj.get("hash")
        )
    
    def parse_stats_line(self, line: str) -> Optional[Dict[str, int]]:
        """Parse rclone stats output line as fallback."""
        match = self.stats_pattern.search(line)
        if match:
            transferred, total, files, errors = match.groups()
            return {
                "transferred": int(transferred),
                "total": int(total),
                "files": int(files),
                "errors": int(errors)
            }
        return None


class RcloneRunner:
    """Execute rclone operations and parse results."""
    
    def __init__(self):
        self.parser = RcloneLogParser()
        if config:
            self.rclone_config = config.get_rclone_config()
        else:
            # Fallback defaults
            self.rclone_config = {
                "transfers": 4,
                "checkers": 8,
                "tpslimit": 10,
                "bwlimit": "0",
                "drive_export": "docx,xlsx,pptx",
                "log_level": "INFO",
            }
    
    def build_rclone_command(
        self,
        src: str,
        dest: str,
        log_file: str,
        additional_flags: List[str] = None
    ) -> List[str]:
        """Build rclone command with standard flags for MasCloner."""
        
        rclone_conf = get_rclone_conf_path()
        
        base_cmd = [
            "rclone", "copy", src, dest,
            f"--config={rclone_conf}",
            f"--log-file={log_file}",
            "--use-json-log",
            f"--log-level={self.rclone_config['log_level']}",
            "--stats-log-level=NOTICE",  # Ensure stats are included in JSON logs
            "--stats=30s",
            "--stats-one-line",
            "--fast-list",
            f"--checkers={self.rclone_config['checkers']}",
            f"--transfers={self.rclone_config['transfers']}",
            f"--tpslimit={self.rclone_config['tpslimit']}",
            f"--bwlimit={self.rclone_config['bwlimit']}",
            # Google Drive specific flags
            "--drive-shared-with-me",
            f"--drive-export-formats={self.rclone_config['drive_export']}",
        ]
        
        if additional_flags:
            base_cmd.extend(additional_flags)
        
        return base_cmd
    
    def run_sync(
        self,
        gdrive_remote: str,
        gdrive_src: str,
        nc_remote: str,
        nc_dest_path: str,
        dry_run: bool = False
    ) -> SyncResult:
        """Execute sync operation and return results."""
        
        result = SyncResult(status="running")
        
        # Ensure log directory exists
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate log filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"sync-{timestamp}.log"
        
        # Build source and destination paths
        src = f"{gdrive_remote}:{gdrive_src}"
        dest = f"{nc_remote}:{nc_dest_path.rstrip('/')}/"
        
        logger.info(f"Starting sync: {src} -> {dest}")
        
        try:
            # Build command
            cmd = self.build_rclone_command(src, dest, str(log_file))
            
            if dry_run:
                cmd.append("--dry-run")
                logger.info("Running in dry-run mode")
            
            logger.info(f"Executing: {' '.join(cmd)}")
            
            # Execute rclone
            result = self._execute_rclone(cmd, str(log_file))
            
            logger.info(f"Sync completed with status: {result.status}")
            logger.info(f"Files: {result.num_added} added, {result.num_updated} updated, {result.errors} errors")
            
            return result
            
        except Exception as e:
            logger.error(f"Sync operation failed: {e}")
            result.status = "error"
            result.error_message = str(e)
            return result
    
    def _execute_rclone(self, cmd: List[str], log_file: str) -> SyncResult:
        """Execute rclone command and parse output."""
        
        result = SyncResult(status="running")
        
        try:
            # Start rclone process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Wait for process completion first
            return_code = process.wait()
            
            # Determine final status
            if return_code == 0:
                result.status = "success"
            elif result.errors > 0:
                result.status = "partial"  # Some files failed
            else:
                result.status = "error"
            
            logger.info(f"rclone exited with code: {return_code}")
            
            # Now parse the log file that rclone created
            if os.path.exists(log_file):
                logger.info(f"Parsing log file: {log_file}")
                with open(log_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Parse JSON log line
                        event = self.parser.parse_line(line)
                        if event:
                            result.events.append(event)
                            logger.debug(f"Created event: {event.action} for {event.file_path}")
                            
                            # Update counters
                            if event.action == "added":
                                result.num_added += 1
                                result.bytes_transferred += event.file_size
                                logger.debug(f"Added file: {event.file_path} ({event.file_size} bytes)")
                            elif event.action == "updated":
                                result.num_updated += 1
                                result.bytes_transferred += event.file_size
                                logger.debug(f"Updated file: {event.file_path} ({event.file_size} bytes)")
                            elif event.action == "error":
                                result.errors += 1
                                logger.debug(f"Error with file: {event.file_path}")
                            elif event.action == "conflict":
                                # Handle conflict by renaming
                                self._handle_conflict(event)
                                result.errors += 1  # Count as error for tracking
                                logger.debug(f"Conflict with file: {event.file_path}")
                        else:
                            # Try to parse as stats line (fallback)
                            stats = self.parser.parse_stats_line(line)
                            if stats:
                                logger.debug(f"Parsed stats: {stats}")
                                # Update result with stats data
                                result.num_added = stats.get("files", 0)
                                result.bytes_transferred = stats.get("transferred", 0)
                                result.errors = stats.get("errors", 0)
                                
                                # Create a generic file event for stats-based sync
                                if stats.get("files", 0) > 0:
                                    generic_event = SyncEvent(
                                        timestamp=datetime.utcnow(),
                                        action="added",  # Assume all files are new for stats
                                        file_path="<stats-based-sync>",
                                        file_size=stats.get("transferred", 0),
                                        message=f"Stats: {stats.get('files', 0)} files, {stats.get('transferred', 0)} bytes",
                                        file_hash=None
                                    )
                                    result.events.append(generic_event)
                                    logger.debug(f"Created stats-based event: {stats.get('files', 0)} files")
                            else:
                                # Log non-parsed lines for debugging
                                if line.startswith('{') and ('file' in line or 'object' in line):
                                    logger.debug(f"Unparsed JSON line: {line[:100]}...")
                                elif "Transferred:" in line:
                                    logger.debug(f"Unparsed stats line: {line}")
            else:
                logger.warning(f"Log file not found: {log_file}")
            
            logger.info(f"Final result: {result.num_added} added, {result.num_updated} updated, {result.errors} errors, {result.bytes_transferred} bytes, {len(result.events)} events")
            
        except subprocess.SubprocessError as e:
            logger.error(f"rclone subprocess error: {e}")
            result.status = "error"
            result.error_message = str(e)
        except Exception as e:
            logger.error(f"Unexpected error during rclone execution: {e}")
            result.status = "error"
            result.error_message = str(e)
        
        return result
    
    def _handle_conflict(self, event: SyncEvent) -> None:
        """Handle file conflict by logging the issue."""
        logger.warning(f"File conflict detected: {event.file_path}")
        logger.warning(f"Conflict message: {event.message}")
        
        # In a real implementation, you might want to:
        # 1. Rename the conflicting file
        # 2. Retry the operation
        # 3. Store conflict information for manual resolution
        
        # For now, we just log it - the actual conflict resolution
        # would happen in rclone or post-processing
        event.action = "conflict"
    
    def test_connection(self, remote: str) -> Tuple[bool, str]:
        """Test connection to a remote."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = ["rclone", "lsd", f"{remote}:", f"--config={rclone_conf}", "--max-depth=1"]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return True, "Connection successful"
            else:
                return False, result.stderr.strip()
                
        except subprocess.TimeoutExpired:
            return False, "Connection timeout"
        except Exception as e:
            return False, str(e)
    
    def list_files(self, remote: str, path: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """List files in a remote path."""
        try:
            rclone_conf = get_rclone_conf_path()
            remote_path = f"{remote}:{path}" if path else f"{remote}:"
            
            cmd = [
                "rclone", "lsjson", remote_path,
                f"--config={rclone_conf}",
                f"--max-depth=1",
                "--no-modtime",
                "--no-mimetype"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                files = json.loads(result.stdout)
                return files[:limit]  # Limit results
            else:
                logger.error(f"Failed to list files: {result.stderr}")
                return []
                
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []
    
    def test_webdav_connection(self, url: str, user: str, password: str, remote_name: str) -> Dict[str, Any]:
        """Test WebDAV connection and create rclone remote if successful."""
        try:
            rclone_conf = get_rclone_conf_path()
            
            # Build rclone config command for WebDAV
            cmd = [
                "rclone", "config", "create", remote_name, "webdav",
                f"url={url}",
                "vendor=nextcloud",
                f"user={user}",
                f"pass={password}",
                f"--config={rclone_conf}"
            ]
            
            # Create the remote
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to create remote: {result.stderr}"
                }
            
            # Test the connection
            test_cmd = [
                "rclone", "lsd", f"{remote_name}:", "--max-depth=1",
                f"--config={rclone_conf}"
            ]
                
            test_result = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if test_result.returncode == 0:
                return {
                    "success": True,
                    "message": "WebDAV remote created and tested successfully"
                }
            else:
                # Remove the failed remote
                self._remove_remote(remote_name)
                return {
                    "success": False,
                    "error": f"Connection test failed: {test_result.stderr}"
                }
                
        except Exception as e:
            logger.error(f"WebDAV test failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def list_folders(self, remote_name: str, path: str = "") -> List[str]:
        """List folders in a remote."""
        try:
            rclone_conf = get_rclone_conf_path()
            remote_path = f"{remote_name}:{path}" if path else f"{remote_name}:"
            base_cmd = [
                "rclone", "lsd", remote_path, "--max-depth=1",
                f"--config={rclone_conf}"
            ]
            
            result = subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0 and remote_name.lower().startswith("gdrive"):
                # Retry listing with shared-drive visibility for Google Workspace accounts
                gworkspace_cmd = base_cmd + ["--drive-shared-with-me"]
                retry = subprocess.run(
                    gworkspace_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if retry.returncode == 0:
                    result = retry
                else:
                    logger.error(
                        "Failed to list Google Drive folders (shared-with-me retry): %s",
                        retry.stderr or "unknown error"
                    )
                    return []
            
            if result.returncode != 0:
                logger.error(f"Failed to list folders: {result.stderr}")
                return []
            
            # Parse the output to extract folder names
            folders = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    # rclone lsd output format: "          -1 2023-01-01 12:00:00        -1 FolderName"
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        folder_name = ' '.join(parts[4:])
                        full_path = f"{path}/{folder_name}" if path else folder_name
                        folders.append(full_path)
            
            return sorted(folders)
            
        except Exception as e:
            logger.error(f"Failed to list folders: {e}")
            return []
    
    def estimate_sync_size(self, source: str, dest: str) -> Dict[str, Any]:
        """Estimate the size of a sync operation using rclone size."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = [
                "rclone", "size", source, "--json",
                f"--config={rclone_conf}"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Longer timeout for size operations
            )
            
            if result.returncode != 0:
                logger.warning(f"Size estimation failed: {result.stderr}")
                return {"size_mb": 0, "file_count": 0, "folder_count": 0}
            
            # Parse JSON output
            size_data = json.loads(result.stdout)
            size_bytes = size_data.get("bytes", 0)
            file_count = size_data.get("count", 0)
            
            return {
                "size_mb": round(size_bytes / 1024 / 1024, 2),
                "file_count": file_count,
                "folder_count": 0  # rclone size doesn't provide folder count
            }
            
        except Exception as e:
            logger.error(f"Size estimation failed: {e}")
            return {"size_mb": 0, "file_count": 0, "folder_count": 0}
    
    def _remove_remote(self, remote_name: str) -> bool:
        """Remove an rclone remote configuration."""
        try:
            rclone_conf = get_rclone_conf_path()
            cmd = [
                "rclone", "config", "delete", remote_name,
                f"--config={rclone_conf}"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Failed to remove remote {remote_name}: {e}")
            return False

    def remove_remote(self, remote_name: str) -> bool:
        """Public wrapper to remove rclone remote configurations."""
        removed = self._remove_remote(remote_name)
        if removed:
            logger.info("rclone remote '%s' removed", remote_name)
        else:
            logger.warning("Unable to remove rclone remote '%s'", remote_name)
        return removed


# Global runner instance
runner = RcloneRunner()


def get_runner() -> RcloneRunner:
    """Get the global rclone runner instance."""
    return runner
