"""SyncExecutor module (ADR 0005, ADR 0007)."""

from .command_builder import RcloneCommandBuilder
from .exceptions import (
    ActiveRunConflictError,
    ExecutionError,
    ExecutionTimeoutError,
    InvalidRunStateError,
    SubprocessLaunchError,
)
from .executor import SyncExecutor
from .models import (
    AbortResult,
    ActiveRunSnapshot,
    FileEventEntry,
    TriggerResult,
)
from .output_parser import RcloneOutputParser

__all__ = [
    "SyncExecutor",
    "ActiveRunSnapshot",
    "TriggerResult",
    "AbortResult",
    "FileEventEntry",
    "RcloneCommandBuilder",
    "RcloneOutputParser",
    "ExecutionError",
    "ActiveRunConflictError",
    "InvalidRunStateError",
    "SubprocessLaunchError",
    "ExecutionTimeoutError",
]
