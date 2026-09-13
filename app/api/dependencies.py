"""FastAPI dependencies for MasCloner.

This module provides dependency injection for shared resources like
the sync executor, scheduler, and configuration module.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .config import ConfigManager
from .scheduler import SyncScheduler

if TYPE_CHECKING:
    from app.execution import SyncExecutor
    from app.configuration import Configuration


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
def get_sync_scheduler() -> SyncScheduler:
    """Get the singleton SyncScheduler instance.

    Uses lru_cache to ensure only one instance exists.
    """
    from .scheduler import sync_scheduler

    return sync_scheduler


@lru_cache(maxsize=1)
def get_sync_executor():
    """Get the singleton SyncExecutor instance."""
    from app.execution import SyncExecutor

    return SyncExecutor.get_instance()


# Dependency functions for FastAPI
def get_scheduler() -> SyncScheduler:
    """FastAPI dependency for SyncScheduler."""
    return get_sync_scheduler()


def get_executor():
    """FastAPI dependency for SyncExecutor."""
    return get_sync_executor()


@lru_cache(maxsize=1)
def get_configuration():
    """Get the singleton Configuration module instance."""
    from app.configuration import Configuration
    from app.api.db import get_db_session

    return Configuration(session_factory=get_db_session)


def get_config() -> ConfigManager:
    """FastAPI dependency for ConfigManager."""
    return get_config_manager()


# Reset functions for testing
def reset_dependencies() -> None:
    """Reset all cached dependencies (for testing)."""
    get_config_manager.cache_clear()
    get_sync_scheduler.cache_clear()
    get_configuration.cache_clear()
    get_sync_executor.cache_clear()
