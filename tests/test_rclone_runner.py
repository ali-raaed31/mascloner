"""Tests for the RcloneRunner class."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.rclone_runner import RcloneLogParser, RcloneRunner, SyncEvent, SyncResult


class TestRcloneLogParser:
    """Tests for the RcloneLogParser class."""

    def test_parse_empty_line(self):
        """Should return None for empty lines."""
        parser = RcloneLogParser()
        assert parser.parse_line("") is None
        assert parser.parse_line("   ") is None

    def test_parse_non_json_line(self):
        """Should return None for non-JSON lines."""
        parser = RcloneLogParser()
        assert parser.parse_line("This is not JSON") is None

    def test_parse_copied_new_action(self):
        """Should parse 'Copied (new)' as 'added' action."""
        parser = RcloneLogParser()
        log_line = (
            '{"level":"info","msg":"Copied (new)",'
            '"object":"test/file.txt","size":1024,'
            '"time":"2024-01-05T12:00:00Z"}'
        )
        event = parser.parse_line(log_line)

        assert event is not None
        assert event.action == "added"
        assert event.file_path == "test/file.txt"
        assert event.file_size == 1024

    def test_parse_copied_replaced_action(self):
        """Should parse 'Copied (replaced)' as 'updated' action."""
        parser = RcloneLogParser()
        log_line = (
            '{"level":"info","msg":"Copied (replaced)",'
            '"object":"test/file.txt","size":2048,'
            '"time":"2024-01-05T12:00:00Z"}'
        )
        event = parser.parse_line(log_line)

        assert event is not None
        assert event.action == "updated"
        assert event.file_size == 2048

    def test_parse_error_level(self):
        """Should parse ERROR level as error action."""
        parser = RcloneLogParser()
        log_line = (
            '{"level":"error","msg":"Failed to copy file",'
            '"object":"bad/file.txt","size":0,'
            '"time":"2024-01-05T12:00:00Z"}'
        )
        event = parser.parse_line(log_line)

        assert event is not None
        assert event.action == "error"

    def test_parse_conflict_detection(self):
        """Should detect conflict scenarios."""
        parser = RcloneLogParser()
        log_line = (
            '{"level":"info","msg":"Skipped: file already exists",'
            '"object":"conflict/file.txt","size":512,'
            '"time":"2024-01-05T12:00:00Z"}'
        )
        event = parser.parse_line(log_line)

        assert event is not None
        assert event.action == "conflict"

    def test_parse_stats_line(self):
        """Should parse stats output."""
        parser = RcloneLogParser()
        stats = parser.parse_stats_line(
            "Transferred: 1024 / 2048, 10 files, 2 errors"
        )

        assert stats is not None
        assert stats["transferred"] == 1024
        assert stats["total"] == 2048
        assert stats["files"] == 10
        assert stats["errors"] == 2


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_default_values(self):
        """Should have correct default values."""
        result = SyncResult(status="running")

        assert result.status == "running"
        assert result.num_added == 0
        assert result.num_updated == 0
        assert result.bytes_transferred == 0
        assert result.errors == 0
        assert result.events == []
        assert result.error_message is None

    def test_with_values(self):
        """Should accept custom values."""
        result = SyncResult(
            status="success",
            num_added=10,
            num_updated=5,
            bytes_transferred=1024 * 1024,
            errors=1,
        )

        assert result.num_added == 10
        assert result.num_updated == 5
        assert result.bytes_transferred == 1024 * 1024
        assert result.errors == 1


class TestRcloneRunner:
    """Tests for RcloneRunner class."""

    def test_build_rclone_command(self):
        """Should build correct rclone command."""
        runner = RcloneRunner()
        cmd = runner.build_rclone_command(
            src="gdrive:TestFolder",
            dest="ncwebdav:Sync/",
            log_file="/tmp/test.log",
        )

        assert "rclone" in cmd
        assert "copy" in cmd
        assert "gdrive:TestFolder" in cmd
        assert "ncwebdav:Sync/" in cmd
        assert "--use-json-log" in cmd

    def test_build_rclone_command_with_flags(self):
        """Should include additional flags."""
        runner = RcloneRunner()
        cmd = runner.build_rclone_command(
            src="gdrive:Test",
            dest="nc:Sync/",
            log_file="/tmp/test.log",
            additional_flags=["--dry-run", "--verbose"],
        )

        assert "--dry-run" in cmd
        assert "--verbose" in cmd

    @pytest.mark.asyncio
    async def test_test_connection_async_success(self):
        """Should return success for valid connection."""
        runner = RcloneRunner()

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"folder1\nfolder2\n", b"")
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            success, message = await runner.test_connection_async("gdrive")

            assert success is True
            assert message == "Connection successful"

    @pytest.mark.asyncio
    async def test_test_connection_async_failure(self):
        """Should return failure for invalid connection."""
        runner = RcloneRunner()

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"Error: connection failed")
            mock_process.returncode = 1
            mock_exec.return_value = mock_process

            success, message = await runner.test_connection_async("invalid")

            assert success is False
            assert "connection failed" in message.lower()

    @pytest.mark.asyncio
    async def test_list_folders_async(self):
        """Should return list of folders."""
        runner = RcloneRunner()

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            # rclone lsd output format
            mock_process.communicate.return_value = (
                b"          -1 2024-01-01 12:00:00        -1 Folder1\n"
                b"          -1 2024-01-01 12:00:00        -1 Folder2\n",
                b"",
            )
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            folders = await runner.list_folders_async("gdrive")

            assert len(folders) == 2
            assert "Folder1" in folders
            assert "Folder2" in folders

