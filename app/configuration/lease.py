"""Process-wide configuration lease abstraction.

Per ADR 0003:
"The same process-wide lease serializes configuration changes with SyncExecutor invocations
so rclone can refresh tokens without a competing writer."
"""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, Optional

from .exceptions import ConfigurationLeaseError


class ConfigurationLease:
    """Manages mutual exclusion for configuration mutations and SyncRun executions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._holder: Optional[str] = None
        self._acquired_at: Optional[float] = None

    @property
    def holder(self) -> Optional[str]:
        """Name or description of current lease holder."""
        return self._holder

    @property
    def acquired_at(self) -> Optional[float]:
        """Timestamp when current lease was acquired."""
        return self._acquired_at

    def is_held(self) -> bool:
        """Return True if lease is currently held."""
        return self._holder is not None

    @contextmanager
    def acquire(self, holder: str, timeout: float = 10.0) -> Iterator[ConfigurationLease]:
        """Acquire lease synchronously with timeout."""
        acquired = self._lock.acquire(timeout=timeout)
        if not acquired:
            raise ConfigurationLeaseError(
                f"Configuration lease is currently held by '{self._holder}', "
                f"could not be acquired by '{holder}' within {timeout:.1f}s timeout."
            )
        try:
            self._holder = holder
            self._acquired_at = time.time()
            yield self
        finally:
            self._holder = None
            self._acquired_at = None
            self._lock.release()

    @asynccontextmanager
    async def acquire_async(
        self, holder: str, timeout: float = 10.0
    ) -> AsyncIterator[ConfigurationLease]:
        """Acquire lease asynchronously with timeout without blocking the event loop."""
        start_time = time.time()
        try:
            await asyncio.wait_for(self._async_lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ConfigurationLeaseError(
                f"Configuration lease is currently held by '{self._holder}', "
                f"could not be acquired by '{holder}' within {timeout:.1f}s timeout."
            )

        elapsed = time.time() - start_time
        remaining_timeout = max(0.01, timeout - elapsed)

        # Offload sync thread lock acquisition so we never block the event loop
        loop = asyncio.get_running_loop()
        acquired = await loop.run_in_executor(None, self._lock.acquire, True, remaining_timeout)
        if not acquired:
            self._async_lock.release()
            raise ConfigurationLeaseError(
                f"Configuration lease is currently held by '{self._holder}', "
                f"could not be acquired by '{holder}' within {timeout:.1f}s timeout."
            )

        try:
            self._holder = holder
            self._acquired_at = time.time()
            yield self
        finally:
            self._holder = None
            self._acquired_at = None
            self._lock.release()
            self._async_lock.release()


_global_process_lease: Optional[ConfigurationLease] = None


def get_process_lease() -> ConfigurationLease:
    """Return the process-wide ConfigurationLease singleton."""
    global _global_process_lease
    if _global_process_lease is None:
        _global_process_lease = ConfigurationLease()
    return _global_process_lease


def reset_process_lease() -> None:
    """Reset the process-wide ConfigurationLease singleton (primarily for tests)."""
    global _global_process_lease
    _global_process_lease = ConfigurationLease()
