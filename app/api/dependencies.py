"""FastAPI dependencies for MasCloner.

This module provides dependency injection for shared resources like
the rclone runner, scheduler, and configuration manager.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .config import ConfigManager
from .rclone_runner import RcloneRunner
from .scheduler import SyncScheduler

if TYPE_CHECKING:
    pass


@lru_cache(maxsize=1)
def get_config_manager() -> ConfigManager:
    """Get the singleton ConfigManager instance.

    Uses lru_cache to ensure only one instance exists.
    """
    from .config import config

    if config is None:
        raise RuntimeError("Configuration manager not initialized")
    return config


@lru_cache(maxsize=1)
def get_rclone_runner() -> RcloneRunner:
    """Get the singleton RcloneRunner instance.

    Uses lru_cache to ensure only one instance exists.
    """
    return RcloneRunner()


@lru_cache(maxsize=1)
def get_sync_scheduler() -> SyncScheduler:
    """Get the singleton SyncScheduler instance.

    Uses lru_cache to ensure only one instance exists.
    """
    from .scheduler import sync_scheduler

    return sync_scheduler


# Dependency functions for FastAPI
def get_runner() -> RcloneRunner:
    """FastAPI dependency for RcloneRunner."""
    return get_rclone_runner()


def get_scheduler() -> SyncScheduler:
    """FastAPI dependency for SyncScheduler."""
    return get_sync_scheduler()


def get_config() -> ConfigManager:
    """FastAPI dependency for ConfigManager."""
    return get_config_manager()


# Reset functions for testing
def reset_dependencies() -> None:
    """Reset all cached dependencies (for testing)."""
    get_config_manager.cache_clear()
    get_rclone_runner.cache_clear()
    get_sync_scheduler.cache_clear()

