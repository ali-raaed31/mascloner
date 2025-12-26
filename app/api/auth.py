"""Authentication middleware and utilities for MasCloner API.

Provides HTTP Basic Auth for API endpoints and token-based authentication.
Authentication can be enabled/disabled via environment variables.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBasic(auto_error=False)


def is_auth_enabled() -> bool:
    """Check if authentication is enabled via environment variable."""
    return os.getenv("MASCLONER_AUTH_ENABLED", "0").lower() in ("1", "true", "yes", "on")


def get_auth_credentials() -> tuple[Optional[str], Optional[str]]:
    """Get configured authentication credentials from environment."""
    username = os.getenv("MASCLONER_AUTH_USERNAME")
    password = os.getenv("MASCLONER_AUTH_PASSWORD")
    return username, password


def verify_credentials(credentials: Optional[HTTPBasicCredentials]) -> bool:
    """Verify the provided credentials against configured values.

    Uses constant-time comparison to prevent timing attacks.
    """
    if not is_auth_enabled():
        return True

    if credentials is None:
        return False

    expected_username, expected_password = get_auth_credentials()

    if not expected_username or not expected_password:
        logger.warning(
            "Authentication is enabled but credentials are not configured. "
            "Set MASCLONER_AUTH_USERNAME and MASCLONER_AUTH_PASSWORD."
        )
        return False

    username_correct = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )

    return username_correct and password_correct


def require_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> Optional[str]:
    """Dependency that requires authentication when enabled.

    Returns the authenticated username if auth is enabled and valid,
    or None if auth is disabled.

    Raises:
        HTTPException: 401 Unauthorized if auth is enabled and credentials are invalid.
    """
    if not is_auth_enabled():
        return None

    if not verify_credentials(credentials):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username if credentials else None


def optional_auth(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
) -> Optional[str]:
    """Dependency that accepts optional authentication.

    Returns username if valid credentials provided, None otherwise.
    Does not raise exceptions for missing/invalid credentials.
    """
    if credentials and verify_credentials(credentials):
        return credentials.username
    return None


# API key authentication (alternative to Basic Auth)
def get_api_key() -> Optional[str]:
    """Get configured API key from environment."""
    return os.getenv("MASCLONER_API_KEY")


def verify_api_key(provided_key: str) -> bool:
    """Verify the provided API key against configured value."""
    expected_key = get_api_key()

    if not expected_key:
        return False

    return secrets.compare_digest(
        provided_key.encode("utf-8"),
        expected_key.encode("utf-8"),
    )

