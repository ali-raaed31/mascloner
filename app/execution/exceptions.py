"""Exceptions for the SyncExecutor module (ADR 0005)."""

from __future__ import annotations

from typing import Optional


class ExecutionError(Exception):
    """Base exception for sync execution errors."""

    def __init__(self, message: str, run_id: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.run_id = run_id


class ActiveRunConflictError(ExecutionError):
    """Raised when a sync cannot start because another run is already active."""
    pass


class InvalidRunStateError(ExecutionError):
    """Raised when an operation is invalid for the run's current state."""
    pass


class SubprocessLaunchError(ExecutionError):
    """Raised when the rclone subprocess fails to launch."""
    pass


class ExecutionTimeoutError(ExecutionError):
    """Raised when sync execution exceeds allowed deadline."""
    pass
