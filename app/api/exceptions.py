"""Standardized exception handling for MasCloner API.

This module provides:
- Custom exception classes for domain-specific errors
- Exception handlers for FastAPI
- Utility functions for consistent error responses

All API endpoints should raise these exceptions instead of returning
ApiResponse(success=False, ...) to maintain consistency.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class MasClonerError(Exception):
    """Base exception for MasCloner application errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ConfigurationError(MasClonerError):
    """Raised when there's a configuration-related error."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )


class ValidationError(MasClonerError):
    """Raised when input validation fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


class NotFoundError(MasClonerError):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            message=f"{resource} not found: {identifier}",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"resource": resource, "identifier": str(identifier)},
        )


class RcloneError(MasClonerError):
    """Raised when an rclone operation fails."""

    def __init__(
        self,
        message: str,
        command: Optional[str] = None,
        stderr: Optional[str] = None,
    ):
        details = {}
        if command:
            details["command"] = command
        if stderr:
            details["stderr"] = stderr
        super().__init__(
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details=details,
        )


class ConnectionError(MasClonerError):
    """Raised when a remote connection fails."""

    def __init__(self, remote: str, message: str):
        super().__init__(
            message=f"Failed to connect to {remote}: {message}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"remote": remote},
        )


class SchedulerError(MasClonerError):
    """Raised when a scheduler operation fails."""

    def __init__(self, message: str, operation: Optional[str] = None):
        details = {}
        if operation:
            details["operation"] = operation
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )


class DatabaseError(MasClonerError):
    """Raised when a database operation fails."""

    def __init__(self, message: str, operation: Optional[str] = None):
        details = {}
        if operation:
            details["operation"] = operation
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )


# Exception handlers for FastAPI
async def mascloner_exception_handler(
    request: Request, exc: MasClonerError
) -> JSONResponse:
    """Handle MasClonerError exceptions."""
    logger.error(
        "MasClonerError: %s (status=%d, details=%s)",
        exc.message,
        exc.status_code,
        exc.details,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "data": exc.details if exc.details else None,
        },
    )


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Handle HTTPException with consistent format."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": str(exc.detail),
            "data": None,
        },
    )


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.exception("Unexpected error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "An unexpected error occurred",
            "data": None,
        },
    )


def register_exception_handlers(app) -> None:
    """Register exception handlers with the FastAPI app.

    Call this in main.py to enable consistent error handling.
    """
    app.add_exception_handler(MasClonerError, mascloner_exception_handler)
    # Note: Don't override default HTTPException handler unless needed
    # app.add_exception_handler(HTTPException, http_exception_handler)
    # app.add_exception_handler(Exception, generic_exception_handler)


# Utility functions
def raise_not_found(resource: str, identifier: Any) -> None:
    """Raise a NotFoundError."""
    raise NotFoundError(resource, identifier)


def raise_validation_error(message: str, **details) -> None:
    """Raise a ValidationError."""
    raise ValidationError(message, details)


def raise_config_error(message: str, **details) -> None:
    """Raise a ConfigurationError."""
    raise ConfigurationError(message, details)

