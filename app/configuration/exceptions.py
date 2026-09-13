"""Exceptions for the typed Configuration module.

Per ADR 0001, errors must be deterministic and must never leak secret values
(passwords, tokens, or encryption keys) in messages or representations.
"""

from __future__ import annotations


class ConfigurationError(Exception):
    """Base exception for all configuration errors."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when a configuration value fails validation or is out of bounds.

    Never contains sensitive credential material or unredacted tokens in its message.
    """


class ConfigurationStoreError(ConfigurationError):
    """Raised when an underlying store adapter (.env, SQLite, rclone.conf) fails."""


class ConfigurationLeaseError(ConfigurationError):
    """Raised when the process-wide configuration lease cannot be acquired."""


class MissingSettingError(ConfigurationValidationError):
    """Raised when a required configuration setting is missing and has no default."""
