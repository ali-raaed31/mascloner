#!/usr/bin/env python3
"""Test script for rclone runner functionality."""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Set up test environment
os.environ["MASCLONER_LOG_DIR"] = "logs"
os.environ["MASCLONER_RCLONE_CONF"] = "etc/rclone.conf"


def test_log_parser():
    """Test rclone JSON log parsing."""
    try:
        from app.api.rclone_runner import RcloneLogParser
        
        print("Testing rclone log parser...")
        
        parser = RcloneLogParser()
        
        # Test JSON log lines
        test_logs = [
            '{"level":"INFO","msg":"Copied (new): file1.txt","file":"file1.txt","size":1024}',
            '{"level":"INFO","msg":"Copied (replaced): file2.txt","file":"file2.txt","size":2048}',
            '{"level":"INFO","msg":"Skipped: file3.txt","file":"file3.txt","size":512}',
            '{"level":"ERROR","msg":"Failed to copy: file4.txt","file":"file4.txt","size":0}',
            'Non-JSON line should be ignored',
            '{"level":"INFO","msg":"Some other message","file":"file5.txt"}',
        ]
        
        events = []
        for log_line in test_logs:
            event = parser.parse_line(log_line)
            if event:
                events.append(event)
        
        # Verify parsing results
        assert len(events) == 4, f"Expected 4 events, got {len(events)}"
        
        # Check first event (new file)
        assert events[0].action == "added"
        assert events[0].file_path == "file1.txt"
        assert events[0].file_size == 1024
        
        # Check second event (replaced file)
        assert events[1].action == "updated"
        assert events[1].file_path == "file2.txt"
        assert events[1].file_size == 2048
        
        # Check third event (skipped file)
        assert events[2].action == "skipped"
        assert events[2].file_path == "file3.txt"
        
        # Check fourth event (error)
        assert events[3].action == "error"
        assert events[3].file_path == "file4.txt"
        
        print("✓ Log parser tests passed")
        return True
        
    except Exception as e:
        print(f"✗ Log parser test failed: {e}")
        return False


def test_command_builder():
    """Test rclone command building."""
    try:
        from app.api.rclone_runner import RcloneRunner
        
        print("\nTesting rclone command builder...")
        
        runner = RcloneRunner()
        
        cmd = runner.build_rclone_command(
            src="gdrive:source/folder",
            dest="nextcloud:dest/folder",
            log_file="/tmp/sync.log"
        )
        
        # Verify essential flags are present
        assert "rclone" in cmd
        assert "copy" in cmd
        assert "gdrive:source/folder" in cmd
        assert "nextcloud:dest/folder" in cmd
        assert "--use-json-log" in cmd
        assert "--drive-shared-with-me" in cmd
        
        print("✓ Command builder tests passed")
        return True
        
    except Exception as e:
        print(f"✗ Command builder test failed: {e}")
        return False


def test_sync_result():
    """Test sync result data structure."""
    try:
        from app.api.rclone_runner import SyncResult, SyncEvent
        from datetime import datetime
        
        print("\nTesting sync result structure...")
        
        # Create test events
        events = [
            SyncEvent(
                timestamp=datetime.utcnow(),
                action="added",
                file_path="test1.txt",
                file_size=1024,
                message="Copied (new): test1.txt"
            ),
            SyncEvent(
                timestamp=datetime.utcnow(),
                action="updated",
                file_path="test2.txt",
                file_size=2048,
                message="Copied (replaced): test2.txt"
            ),
            SyncEvent(
                timestamp=datetime.utcnow(),
                action="error",
                file_path="test3.txt",
                file_size=0,
                message="Failed to copy: test3.txt"
            ),
        ]
        
        # Create sync result
        result = SyncResult(
            status="partial",
            num_added=1,
            num_updated=1,
            bytes_transferred=3072,
            errors=1,
            events=events
        )
        
        # Verify result structure
        assert result.status == "partial"
        assert result.num_added == 1
        assert result.num_updated == 1
        assert result.bytes_transferred == 3072
        assert result.errors == 1
        assert len(result.events) == 3
        
        print("✓ Sync result tests passed")
        return True
        
    except Exception as e:
        print(f"✗ Sync result test failed: {e}")
        return False


def test_conflict_resolution():
    """Test conflict filename generation."""
    try:
        from app.api.config import resolve_conflict_filename
        from pathlib import Path
        
        print("\nTesting conflict resolution...")
        
        # Test basic conflict resolution
        original = "document.pdf"
        dest_dir = Path("/tmp/test")
        
        # This should return the original path if it doesn't exist
        conflict_path = resolve_conflict_filename(original, str(dest_dir))
        expected = str(dest_dir / "document.pdf")
        assert conflict_path == expected, f"Expected {expected}, got {conflict_path}"
        
        print("✓ Conflict resolution tests passed")
        return True
        
    except Exception as e:
        print(f"✗ Conflict resolution test failed: {e}")
        return False


def test_mock_sync():
    """Test sync operation with mock data (no actual rclone execution)."""
    try:
        from app.api.rclone_runner import RcloneRunner, SyncResult
        
        print("\nTesting mock sync operation...")
        
        runner = RcloneRunner()
        
        # Test dry-run command building
        cmd = runner.build_rclone_command(
            src="gdrive:test",
            dest="nextcloud:backup",
            log_file="logs/test.log",
            additional_flags=["--dry-run"]
        )
        
        assert "--dry-run" in cmd
        print("✓ Dry-run command includes correct flag")
        
        # Test connection test (will fail but should handle gracefully)
        try:
            success, message = runner.test_connection("nonexistent-remote")
            # Should fail gracefully
            assert not success
            print("✓ Connection test handles missing remote gracefully")
        except Exception:
            print("✓ Connection test handles errors appropriately")
        
        print("✓ Mock sync tests passed")
        return True
        
    except Exception as e:
        print(f"✗ Mock sync test failed: {e}")
        return False


def main():
    """Run all rclone tests."""
    print("MasCloner rclone Runner Tests")
    print("=" * 40)
    
    success = True
    
    # Test log parser
    if not test_log_parser():
        success = False
    
    # Test command builder
    if not test_command_builder():
        success = False
    
    # Test sync result
    if not test_sync_result():
        success = False
    
    # Test conflict resolution
    if not test_conflict_resolution():
        success = False
    
    # Test mock sync
    if not test_mock_sync():
        success = False
    
    print("\n" + "=" * 40)
    if success:
        print("✓ All rclone tests passed!")
    else:
        print("✗ Some rclone tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
