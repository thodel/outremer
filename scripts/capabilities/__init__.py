"""Provider-neutral capability adapters for Outremer."""

from .contracts import (
    ArtifactRef,
    Availability,
    CapabilityDescriptor,
    CapabilityError,
    InvocationRecord,
    ToolSpec,
)
from .registry import CapabilityRegistry

__all__ = [
    "ArtifactRef",
    "Availability",
    "CapabilityDescriptor",
    "CapabilityError",
    "CapabilityRegistry",
    "InvocationRecord",
    "ToolSpec",
]
