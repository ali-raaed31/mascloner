#!/usr/bin/env python3
"""Test script to reproduce the rclone subprocess issue."""

import subprocess
import sys

def test_rclone_command():
    """Test the exact rclone command that's failing."""
    
    cmd = [
        "rclone", "copy",
        "gdrive:Training proposal",
        "ncwebdav:Cloner_files/from google drive/",
        "--config=/srv/mascloner/etc/rclone.conf",
        "--dry-run",
        "--log-level=INFO"
    ]
    
    print("=" * 80)
    print("Testing rclone subprocess call")
    print("=" * 80)
    print(f"\nCommand has {len(cmd)} elements:")
    for i, arg in enumerate(cmd):
        print(f"  [{i}]: {repr(arg)}")
    
    print(f"\nJoined command (for display only):")
    print(f"  {' '.join(cmd)}")
    
    print(f"\nExecuting subprocess...")
    print("=" * 80)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print(f"\nReturn code: {result.returncode}")
        print(f"\nSTDOUT:\n{result.stdout}")
        print(f"\nSTDERR:\n{result.stderr}")
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"\nException: {e}")
        return False

if __name__ == "__main__":
    success = test_rclone_command()
    sys.exit(0 if success else 1)
