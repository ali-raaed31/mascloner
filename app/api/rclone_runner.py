"""rclone execution and JSON log parsing for MasCloner."""

import subprocess
import json
import os
import logging
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
    """Parser for rclone JSON log output."""
    
    # Map rclone log messages to our action types
    ACTION_MAP = {
        "Copied (new)": "added",
        "Copied (replaced)": "updated", 
        "Copied": "added",  # Generic copy
        "Skipped": "skipped",
        "Can't copy": "error",
        "Failed to copy": "error",
        "ERROR": "error",
    }
    
    def parse_line(self, line: str) -> Optional[SyncEvent]:
        """Parse a single JSON log line from rclone."""
        if not line.strip():
            return None
            
        try:
            obj = json.loads(line.strip())
        except (json.JSONDecodeError, AttributeError):
            # Not a JSON line, might be stats or other output
            return None
            
        level = obj.get("level", "").upper()
        msg = obj.get("msg", "")
        file_path = obj.get("file") or obj.get("object") or ""
        file_size = int(obj.get("size", 0))
        
        # Determine action from message content
        action = None
        
        # Check for error level first
        if level == "ERROR":
            action = "error"
        else:
            # Look for action indicators in message
            for key, val in self.ACTION_MAP.items():
                if key in msg:
                    action = val
                    break
        
        # Skip if no recognizable action
        if not action:
            return None
        
        # Check for conflict scenarios
        if "already exists" in msg.lower() or "conflict" in msg.lower():
            action = "conflict"
        
        return SyncEvent(
            timestamp=datetime.utcnow(),
            action=action,
            file_path=file_path,
            file_size=file_size,
            message=msg,
            file_hash=obj.get("hash")
        )


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
            "--log-format=DATE,TIME,LEVEL,PID",
            f"--log-level={self.rclone_config['log_level']}",
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
            
            # Parse output in real-time
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                
                # Parse JSON log line
                event = self.parser.parse_line(line)
                if event:
                    result.events.append(event)
                    
                    # Update counters
                    if event.action == "added":
                        result.num_added += 1
                        result.bytes_transferred += event.file_size
                    elif event.action == "updated":
                        result.num_updated += 1
                        result.bytes_transferred += event.file_size
                    elif event.action == "error":
                        result.errors += 1
                    elif event.action == "conflict":
                        # Handle conflict by renaming
                        self._handle_conflict(event)
                        result.errors += 1  # Count as error for tracking
            
            # Wait for process completion
            return_code = process.wait()
            
            # Determine final status
            if return_code == 0:
                result.status = "success"
            elif result.errors > 0:
                result.status = "partial"  # Some files failed
            else:
                result.status = "error"
            
            logger.info(f"rclone exited with code: {return_code}")
            
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


# Global runner instance
runner = RcloneRunner()


def get_runner() -> RcloneRunner:
    """Get the global rclone runner instance."""
    return runner
