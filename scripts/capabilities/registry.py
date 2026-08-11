"""Required/optional capability policy, discovery, invocation, and audit."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    ArtifactRef,
    Availability,
    CapabilityAdapter,
    CapabilityError,
    InvocationRecord,
)
from .provenance import JsonlInvocationLog


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapabilityRegistry:
    def __init__(
        self,
        *,
        invocation_log: JsonlInvocationLog | None = None,
        audit_required: bool = True,
    ) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}
        self._availability: dict[str, Availability] = {}
        self.invocation_log = invocation_log
        self.audit_required = audit_required

    def register(self, adapter: CapabilityAdapter) -> None:
        cap_id = adapter.descriptor.id
        if cap_id in self._adapters:
            raise ValueError(f"duplicate capability id: {cap_id}")
        self._adapters[cap_id] = adapter

    def descriptors(self) -> list[dict[str, Any]]:
        return [self._adapters[key].descriptor.to_dict() for key in sorted(self._adapters)]

    def discover(self) -> dict[str, Any]:
        errors: list[str] = []
        results: list[Availability] = []
        for cap_id in sorted(self._adapters):
            adapter = self._adapters[cap_id]
            if not adapter.descriptor.enabled:
                availability = Availability(cap_id, "disabled", timestamp())
            else:
                try:
                    availability = adapter.discover()
                except Exception as exc:  # provider failures become explicit state
                    availability = Availability(
                        cap_id,
                        "unavailable",
                        timestamp(),
                        detail=f"{type(exc).__name__}: {exc}",
                    )
            self._availability[cap_id] = availability
            results.append(availability)
            if adapter.descriptor.required and availability.status != "available":
                errors.append(f"required capability {cap_id}: {availability.status}")
        return {
            "schema_version": 1,
            "checked_at": timestamp(),
            "status": "pass" if not errors else "fail",
            "capabilities": [item.to_dict() for item in results],
            "errors": errors,
        }

    def require_ready(self) -> None:
        report = self.discover()
        if report["status"] != "pass":
            raise CapabilityError("; ".join(report["errors"]))

    def invoke(
        self,
        capability_id: str,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        run_id: str,
        inputs: list[ArtifactRef] | None = None,
        output_refs: list[ArtifactRef] | None = None,
    ) -> Any:
        adapter = self._adapters.get(capability_id)
        if adapter is None:
            raise CapabilityError(f"unknown capability: {capability_id}")
        if self.audit_required and self.invocation_log is None:
            raise CapabilityError("capability invocation requires an append-only audit log")
        descriptor = adapter.descriptor
        availability = self._availability.get(capability_id)
        if availability is None:
            availability = adapter.discover() if descriptor.enabled else Availability(
                capability_id, "disabled", timestamp()
            )
            self._availability[capability_id] = availability
            descriptor = adapter.descriptor  # discovery may populate dynamic tools
        known_tools = {tool.id for tool in descriptor.tools}
        if tool_id not in known_tools:
            raise CapabilityError(f"{capability_id}: unknown tool {tool_id}")
        started_at = timestamp()
        start = time.monotonic()
        status = "success"
        error_type = None
        try:
            if availability.status != "available":
                status = "blocked"
                raise CapabilityError(
                    f"{capability_id} is {availability.status}: {availability.detail or ''}".strip()
                )
            return adapter.invoke(tool_id, arguments)
        except Exception as exc:
            if status != "blocked":
                status = "error"
            error_type = type(exc).__name__
            raise
        finally:
            if self.invocation_log:
                self.invocation_log.append(
                    InvocationRecord(
                        invocation_id=str(uuid.uuid4()),
                        run_id=run_id,
                        capability_id=capability_id,
                        tool_id=tool_id,
                        contract_version=descriptor.contract_version,
                        provider_version=availability.provider_version,
                        started_at=started_at,
                        finished_at=timestamp(),
                        latency_ms=round((time.monotonic() - start) * 1000),
                        status=status,  # type: ignore[arg-type]
                        inputs=inputs or [],
                        outputs=output_refs or [],
                        error_type=error_type,
                    )
                )
