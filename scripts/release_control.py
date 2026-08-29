#!/usr/bin/env python3
"""Preflight, provenance gate, and immutable manifest for tei releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_MARKERS = ("key", "token", "password", "secret", "credential")
ALLOWED_CAPABILITY_KINDS = {"http", "http_json", "openai_models", "atr"}


class ReleaseControlError(RuntimeError):
    """A release control rejected configuration, provenance, or promotion."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseControlError(f"{path}: expected a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_endpoint(raw: str) -> str:
    """Return a credential-free endpoint or reject unsafe endpoint syntax."""
    parsed = urllib.parse.urlsplit(raw.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ReleaseControlError("endpoint must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ReleaseControlError("endpoint must not contain credentials, query, or fragment")
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, "", ""))


def join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def auth_headers(capability: dict[str, Any], environ: dict[str, str]) -> dict[str, str]:
    mode = capability.get("auth", "none")
    credential_name = capability.get("credential_env")
    credential = environ.get(credential_name, "") if credential_name else ""
    if mode in {"bearer", "x-api-key"} and not credential:
        raise ReleaseControlError(f"{capability['id']}: missing {credential_name}")
    if mode == "bearer" or (mode == "bearer-optional" and credential):
        return {"Authorization": f"Bearer {credential}"}
    if mode == "x-api-key":
        return {"X-API-Key": credential}
    if mode not in {"none", "bearer-optional"}:
        raise ReleaseControlError(f"{capability['id']}: unsupported auth mode {mode}")
    return {}


def request(
    url: str, headers: dict[str, str], timeout: float, *, expect_json: bool
) -> tuple[int, Any, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024)
            payload = json.loads(body) if expect_json else None
            return response.status, payload, dict(response.headers.items())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ReleaseControlError(f"request failed for {safe_endpoint(url)}: {exc}") from exc


def extract_version(payload: Any, headers: dict[str, str]) -> str | None:
    if isinstance(payload, dict):
        for key in ("version", "service_version", "api_version"):
            if payload.get(key) is not None:
                return str(payload[key])
    for key in ("X-Service-Version", "X-API-Version"):
        if headers.get(key):
            return headers[key]
    return None


def model_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    raw = payload.get("data", payload.get("models", []))
    if not isinstance(raw, list):
        return set()
    return {
        str(item.get("id") or item.get("name"))
        for item in raw
        if isinstance(item, dict) and (item.get("id") or item.get("name"))
    }


def check_capability(
    capability: dict[str, Any], environ: dict[str, str]
) -> dict[str, Any]:
    cap_id = str(capability.get("id") or "")
    kind = capability.get("kind")
    if not cap_id or kind not in ALLOWED_CAPABILITY_KINDS:
        raise ReleaseControlError(f"invalid capability declaration: {capability!r}")
    url_env = str(capability.get("url_env") or "")
    raw_url = environ.get(url_env, "")
    if not raw_url:
        raise ReleaseControlError(f"{cap_id}: missing {url_env}")
    endpoint = safe_endpoint(raw_url)
    headers = auth_headers(capability, environ)
    timeout = float(capability.get("timeout_seconds", 10))
    health_path = str(capability.get("health_path", "/"))
    expect_json = kind in {"http_json", "openai_models", "atr"}
    status, payload, response_headers = request(
        join_url(endpoint, health_path), headers, timeout, expect_json=expect_json
    )
    if status < 200 or status >= 400:
        raise ReleaseControlError(f"{cap_id}: health returned HTTP {status}")

    models: set[str] = model_ids(payload) if kind == "openai_models" else set()
    if kind == "atr":
        models_path = str(capability.get("models_path", "/models"))
        _, models_payload, model_headers = request(
            join_url(endpoint, models_path), headers, timeout, expect_json=True
        )
        models = model_ids(models_payload)
        response_headers.update(model_headers)
    required_model_envs = capability.get("required_model_envs", [])
    missing_model_envs = [name for name in required_model_envs if not environ.get(name)]
    if missing_model_envs:
        raise ReleaseControlError(
            f"{cap_id}: required model environment value(s) missing: {missing_model_envs}"
        )
    required_models = {environ[name] for name in required_model_envs}
    missing_models = sorted(required_models - models)
    if missing_models:
        raise ReleaseControlError(f"{cap_id}: required model(s) missing: {missing_models}")
    return {
        "id": cap_id,
        "required": bool(capability.get("required")),
        "status": "available",
        "endpoint": endpoint,
        "version": extract_version(payload, response_headers),
        "models": sorted(models),
    }


def check_storage(item: dict[str, Any], environ: dict[str, str]) -> dict[str, Any]:
    path_env = str(item.get("path_env") or "")
    value = environ.get(path_env, "")
    if not value:
        raise ReleaseControlError(f"{item.get('id')}: missing {path_env}")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        raise ReleaseControlError(f"{item.get('id')}: unsafe storage path")
    if not path.is_dir():
        raise ReleaseControlError(f"{item.get('id')}: storage directory does not exist")
    if not os.access(path, os.R_OK | os.X_OK):
        raise ReleaseControlError(f"{item.get('id')}: storage directory is not readable")
    if item.get("writable") and not os.access(path, os.W_OK):
        raise ReleaseControlError(f"{item.get('id')}: storage directory is not writable")
    return {
        "id": str(item.get("id")),
        "path": str(path),
        "writable": bool(item.get("writable")),
        "status": "available",
    }


def preflight(config: dict[str, Any], environ: dict[str, str]) -> dict[str, Any]:
    if config.get("schema_version") != 1:
        raise ReleaseControlError("unsupported live-capabilities schema")
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for capability in config.get("capabilities", []):
        try:
            results.append(check_capability(capability, environ))
        except ReleaseControlError as exc:
            result = {
                "id": str(capability.get("id")),
                "required": bool(capability.get("required")),
                "status": "unavailable",
                "error": str(exc),
            }
            results.append(result)
            if result["required"]:
                errors.append(str(exc))
    storage_results: list[dict[str, Any]] = []
    for item in config.get("storage", []):
        try:
            storage_results.append(check_storage(item, environ))
        except ReleaseControlError as exc:
            storage_results.append({"id": item.get("id"), "status": "unavailable", "error": str(exc)})
            errors.append(str(exc))

    try:
        from evidence_model import SCHEMA_VERSION
    except ImportError:
        from scripts.evidence_model import SCHEMA_VERSION
    expected_schema = str((config.get("schema") or {}).get("evidence") or "")
    if expected_schema != SCHEMA_VERSION:
        errors.append(
            f"evidence schema mismatch: config={expected_schema!r}, code={SCHEMA_VERSION!r}"
        )
    return {
        "schema_version": 1,
        "checked_at": now(),
        "profile": config.get("profile"),
        "status": "pass" if not errors else "fail",
        "capabilities": results,
        "storage": storage_results,
        "schemas": {"evidence": SCHEMA_VERSION},
        "errors": errors,
    }


def gate_report(
    report: dict[str, Any], *, require_recognition: bool, expected_model: str | None
) -> dict[str, Any]:
    errors: list[str] = []
    docs_total = int(report.get("docs_total", 0))
    docs_ok = int(report.get("docs_ok", 0))
    docs_failed = int(report.get("docs_failed", 0))
    if docs_total < 1 or docs_ok != docs_total or docs_failed:
        errors.append(
            f"document outcome is not publication-grade: total={docs_total}, ok={docs_ok}, failed={docs_failed}"
        )
    by_engine = (report.get("extraction") or {}).get("documents_by_engine") or {}
    unexpected = sorted(engine for engine, count in by_engine.items() if count and engine != "gpustack")
    if unexpected or not by_engine or sum(by_engine.values()) != docs_total:
        errors.append(f"unexpected extraction engines: {by_engine!r}")
    if report.get("llm_provider") != "gpustack":
        errors.append(f"llm_provider must be gpustack, got {report.get('llm_provider')!r}")
    degradation = (report.get("extraction") or {}).get("degradation") or {}
    if int(degradation.get("fallback_chunks", 0)):
        errors.append(f"fallback chunks are forbidden: {degradation!r}")
    if expected_model and report.get("extraction_model") != expected_model:
        errors.append(
            f"extraction model mismatch: expected {expected_model!r}, got {report.get('extraction_model')!r}"
        )
    recognition = (report.get("recognition") or {}).get("engines_used") or {}
    if require_recognition and not any(int(count) > 0 for count in recognition.values()):
        errors.append("representative scanned fixture did not record a recognition engine")
    if report.get("failures"):
        errors.append("run report contains failures")
    return {
        "schema_version": 1,
        "checked_at": now(),
        "status": "pass" if not errors else "fail",
        "require_recognition": require_recognition,
        "observed": {
            "documents_by_engine": by_engine,
            "recognition_engines": recognition,
            "extraction_model": report.get("extraction_model"),
        },
        "errors": errors,
    }


def git_value(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def dependency_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            result[name.casefold()] = dist.version
    return dict(sorted(result.items()))


def assert_no_secret_keys(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            if any(marker in lowered for marker in SECRET_MARKERS):
                raise ReleaseControlError(f"secret-like key forbidden in manifest: {path}.{key}")
            assert_no_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_secret_keys(child, f"{path}[{index}]")


def build_manifest(
    preflight_result: dict[str, Any], reports: list[Path], image_digest: str | None
) -> dict[str, Any]:
    if preflight_result.get("status") != "pass":
        raise ReleaseControlError("cannot manifest a failed preflight")
    if image_digest and not image_digest.startswith("sha256:"):
        raise ReleaseControlError("image digest must use sha256:<hex>")
    lock = Path("requirements.lock.txt")
    report_entries = [
        {"path": str(path), "sha256": sha256_file(path), "gate": gate_report(read_json(path), require_recognition=False, expected_model=None)}
        for path in reports
    ]
    if any(entry["gate"]["status"] != "pass" for entry in report_entries):
        raise ReleaseControlError("cannot manifest a run report that fails the provenance gate")
    capabilities = [
        {
            key: capability.get(key)
            for key in ("id", "status", "endpoint", "version", "models")
            if capability.get(key) is not None
        }
        for capability in preflight_result.get("capabilities", [])
    ]
    manifest = {
        "schema_version": 1,
        "created_at": now(),
        "profile": preflight_result.get("profile"),
        "source": {
            "commit": git_value("rev-parse", "HEAD"),
            "tree": git_value("rev-parse", "HEAD^{tree}"),
            "dirty": bool(git_value("status", "--porcelain", "--untracked-files=no")),
        },
        "artifact": {"image_digest": image_digest},
        "runtime": {"python": platform.python_version()},
        "dependencies": {
            "lock_sha256": sha256_file(lock),
            "installed": dependency_versions(),
        },
        "models": {
            "text": os.environ.get("GPUSTACK_MODEL_TEXT") or os.environ.get("EXTRACTION_MODEL"),
            "vision": os.environ.get("GPUSTACK_MODEL_VISION") or os.environ.get("QWEN3_VL_MODEL"),
            "orchestrator": os.environ.get("GPUSTACK_MODEL_ORCHESTRATOR") or os.environ.get("ORCHESTRATOR_MODEL"),
        },
        "capabilities": capabilities,
        "schemas": preflight_result.get("schemas", {}),
        "migrations": {"status": "validated", "evidence_schema": preflight_result.get("schemas", {}).get("evidence")},
        "run_reports": report_entries,
    }
    if manifest["source"]["dirty"]:
        raise ReleaseControlError("release manifest requires a clean checkout")
    assert_no_secret_keys(manifest)
    return manifest


def command_preflight(args: argparse.Namespace) -> int:
    result = preflight(read_json(args.config), dict(os.environ))
    write_json(args.output, result)
    if result["status"] != "pass":
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


def command_gate(args: argparse.Namespace) -> int:
    result = gate_report(
        read_json(args.report),
        require_recognition=args.require_recognition,
        expected_model=args.expected_model,
    )
    write_json(args.output, result)
    if result["status"] != "pass":
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


def command_manifest(args: argparse.Namespace) -> int:
    manifest = build_manifest(read_json(args.preflight), args.report, args.image_digest)
    write_json(args.output, manifest)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(required=True)
    preflight_parser = commands.add_parser("preflight")
    preflight_parser.add_argument("--config", type=Path, required=True)
    preflight_parser.add_argument("--output", type=Path, required=True)
    preflight_parser.set_defaults(func=command_preflight)
    gate_parser = commands.add_parser("gate")
    gate_parser.add_argument("--report", type=Path, required=True)
    gate_parser.add_argument("--output", type=Path, required=True)
    gate_parser.add_argument("--require-recognition", action="store_true")
    gate_parser.add_argument("--expected-model")
    gate_parser.set_defaults(func=command_gate)
    manifest_parser = commands.add_parser("manifest")
    manifest_parser.add_argument("--preflight", type=Path, required=True)
    manifest_parser.add_argument("--report", type=Path, action="append", required=True)
    manifest_parser.add_argument("--image-digest")
    manifest_parser.add_argument("--output", type=Path, required=True)
    manifest_parser.set_defaults(func=command_manifest)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except (ReleaseControlError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
