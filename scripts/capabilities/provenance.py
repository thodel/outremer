"""Append-only, payload-free capability invocation provenance."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .contracts import InvocationRecord

SECRET_MARKERS = ("password", "secret", "token", "api_key", "authorization", "credential")


def reject_secret_keys(value: Any, path: str = "record") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(marker in str(key).casefold() for marker in SECRET_MARKERS):
                raise ValueError(f"secret-like key forbidden in provenance: {path}.{key}")
            reject_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_keys(child, f"{path}[{index}]")


class JsonlInvocationLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: InvocationRecord) -> None:
        value = record.to_dict()
        reject_secret_keys(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        fd = os.open(self.path, flags, 0o640)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
