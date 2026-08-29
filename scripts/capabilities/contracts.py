"""Stable contracts shared by every infrastructure adapter."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

CapabilityStatus = Literal["available", "unavailable", "disabled", "incompatible"]
InvocationStatus = Literal["success", "error", "blocked"]


class CapabilityError(RuntimeError):
    """A capability is unavailable, incompatible, disabled, or failed."""


@dataclass(frozen=True)
class ToolSpec:
    id: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    mutating: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    provider: str
    contract: str
    contract_version: str
    required: bool
    enabled: bool
    tools: tuple[ToolSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["tools"] = [tool.to_dict() for tool in self.tools]
        return result


@dataclass(frozen=True)
class Availability:
    capability_id: str
    status: CapabilityStatus
    checked_at: str
    provider_version: str | None = None
    endpoint: str | None = None
    tools: tuple[str, ...] = ()
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["tools"] = list(self.tools)
        return result


@dataclass(frozen=True)
class ArtifactRef:
    """Reference plus digest; invocation logs never contain artifact payloads."""

    uri: str
    sha256: str
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.uri:
            raise ValueError("artifact URI is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("artifact sha256 must be 64 lowercase hexadecimal characters")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvocationRecord:
    invocation_id: str
    run_id: str
    capability_id: str
    tool_id: str
    contract_version: str
    provider_version: str | None
    started_at: str
    finished_at: str
    latency_ms: int
    status: InvocationStatus
    inputs: list[ArtifactRef] = field(default_factory=list)
    outputs: list[ArtifactRef] = field(default_factory=list)
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["inputs"] = [item.to_dict() for item in self.inputs]
        result["outputs"] = [item.to_dict() for item in self.outputs]
        return result


class CapabilityAdapter(Protocol):
    descriptor: CapabilityDescriptor

    def discover(self) -> Availability: ...

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> Any: ...
