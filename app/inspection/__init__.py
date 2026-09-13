"""Side-effect-free EndpointInspector module (ADR 0005)."""

from .exceptions import (
    InspectionAuthError,
    InspectionError,
    InspectionNetworkError,
    InspectionTimeoutError,
    InspectionValidationError,
    UnsupportedEndpointError,
)
from .inspector import EndpointInspector
from .models import (
    BrowseResult,
    ConnectionTestResult,
    EndpointConcept,
    EndpointStatusResult,
    FolderEntry,
    SizeEstimationResult,
)

__all__ = [
    "EndpointInspector",
    "EndpointConcept",
    "FolderEntry",
    "BrowseResult",
    "ConnectionTestResult",
    "EndpointStatusResult",
    "SizeEstimationResult",
    "InspectionError",
    "UnsupportedEndpointError",
    "InspectionTimeoutError",
    "InspectionAuthError",
    "InspectionNetworkError",
    "InspectionValidationError",
]
