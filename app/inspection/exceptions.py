"""Exceptions for the EndpointInspector module."""

from __future__ import annotations


class InspectionError(Exception):
    """Base exception for all inspection errors."""


class UnsupportedEndpointError(InspectionError):
    """Raised when an unsupported remote name or endpoint concept is requested."""


class InspectionTimeoutError(InspectionError):
    """Raised when an inspection subprocess times out."""


class InspectionAuthError(InspectionError):
    """Raised when inspection fails due to invalid or expired credentials."""


class InspectionNetworkError(InspectionError):
    """Raised when inspection fails due to network or connection errors."""


class InspectionValidationError(InspectionError):
    """Raised when inspection request parameters are invalid."""
