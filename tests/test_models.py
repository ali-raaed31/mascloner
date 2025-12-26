"""Tests for SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.api.models import ConfigKV, FileEvent, Run


class TestRunModel:
    """Tests for the Run model."""

    def test_create_run(self, test_session: Session):
        """Should create a run with required fields."""
        run = Run(
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        assert run.id is not None
        assert run.status == "running"
        assert run.num_added == 0
        assert run.num_updated == 0
        assert run.bytes_transferred == 0
        assert run.errors == 0

    def test_run_with_all_fields(self, test_session: Session):
        """Should create a run with all fields."""
        run = Run(
            status="success",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            num_added=10,
            num_updated=5,
            bytes_transferred=1024 * 1024,
            errors=0,
            log_path="/var/log/sync.log",
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        assert run.num_added == 10
        assert run.num_updated == 5
        assert run.bytes_transferred == 1024 * 1024
        assert run.log_path == "/var/log/sync.log"

    def test_run_events_relationship(self, test_session: Session):
        """Should correctly handle events relationship."""
        run = Run(
            status="success",
            started_at=datetime.now(timezone.utc),
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        # Add events
        event1 = FileEvent(
            run_id=run.id,
            action="added",
            file_path="file1.txt",
            file_size=100,
            timestamp=datetime.now(timezone.utc),
        )
        event2 = FileEvent(
            run_id=run.id,
            action="updated",
            file_path="file2.txt",
            file_size=200,
            timestamp=datetime.now(timezone.utc),
        )
        test_session.add_all([event1, event2])
        test_session.commit()
        test_session.refresh(run)

        assert len(run.events) == 2


class TestFileEventModel:
    """Tests for the FileEvent model."""

    def test_create_event(self, test_session: Session):
        """Should create an event with required fields."""
        # Create parent run first
        run = Run(status="running", started_at=datetime.now(timezone.utc))
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        event = FileEvent(
            run_id=run.id,
            action="added",
            file_path="documents/report.pdf",
            file_size=1024 * 100,
            timestamp=datetime.now(timezone.utc),
        )
        test_session.add(event)
        test_session.commit()
        test_session.refresh(event)

        assert event.id is not None
        assert event.action == "added"
        assert event.file_path == "documents/report.pdf"
        assert event.file_size == 1024 * 100

    def test_event_with_optional_fields(self, test_session: Session):
        """Should create an event with optional fields."""
        run = Run(status="running", started_at=datetime.now(timezone.utc))
        test_session.add(run)
        test_session.commit()

        event = FileEvent(
            run_id=run.id,
            action="added",
            file_path="file.txt",
            file_size=500,
            timestamp=datetime.now(timezone.utc),
            file_hash="abc123def456",
            message="File copied successfully",
        )
        test_session.add(event)
        test_session.commit()
        test_session.refresh(event)

        assert event.file_hash == "abc123def456"
        assert event.message == "File copied successfully"


class TestConfigKVModel:
    """Tests for the ConfigKV model."""

    def test_create_config(self, test_session: Session):
        """Should create a config entry."""
        config_entry = ConfigKV(key="gdrive_src", value="My Drive/Sync")
        test_session.add(config_entry)
        test_session.commit()
        test_session.refresh(config_entry)

        assert config_entry.key == "gdrive_src"
        assert config_entry.value == "My Drive/Sync"

    def test_update_config(self, test_session: Session):
        """Should update existing config entry via merge."""
        # Create initial config
        config_entry = ConfigKV(key="interval_min", value="5")
        test_session.add(config_entry)
        test_session.commit()

        # Update via merge
        updated_entry = ConfigKV(key="interval_min", value="10")
        test_session.merge(updated_entry)
        test_session.commit()

        # Verify update
        from sqlalchemy import select

        result = test_session.execute(
            select(ConfigKV).where(ConfigKV.key == "interval_min")
        ).scalar_one()
        assert result.value == "10"

