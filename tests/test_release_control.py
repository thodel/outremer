from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import promote_release, release_control


def good_report(*, recognition: bool = False) -> dict:
    return {
        "docs_total": 1,
        "docs_ok": 1,
        "docs_failed": 0,
        "llm_provider": "gpustack",
        "extraction_model": "text-model",
        "failures": [],
        "extraction": {
            "documents_by_engine": {"gpustack": 1},
            "degradation": {"chunks": 1, "fallback_chunks": 0, "reasons": []},
        },
        "recognition": {"engines_used": {"qwen3-vl": 1} if recognition else {}},
    }


def test_gate_accepts_text_and_scanned_production_runs() -> None:
    text = release_control.gate_report(
        good_report(), require_recognition=False, expected_model="text-model"
    )
    scan = release_control.gate_report(
        good_report(recognition=True),
        require_recognition=True,
        expected_model="text-model",
    )
    assert text["status"] == "pass"
    assert scan["status"] == "pass"


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda r: r.update(llm_provider="heuristic"), "llm_provider"),
        (
            lambda r: r["extraction"].update(documents_by_engine={"mixed": 1}),
            "unexpected extraction engines",
        ),
        (
            lambda r: r["extraction"]["degradation"].update(fallback_chunks=1),
            "fallback chunks",
        ),
        (lambda r: r.update(docs_failed=1, docs_ok=0), "document outcome"),
        (lambda r: r.update(extraction_model="wrong"), "model mismatch"),
    ],
)
def test_gate_rejects_non_production_provenance(mutation, error: str) -> None:
    report = good_report()
    mutation(report)
    result = release_control.gate_report(
        report, require_recognition=False, expected_model="text-model"
    )
    assert result["status"] == "fail"
    assert any(error in item for item in result["errors"])


def test_gate_requires_recognition_for_scanned_fixture() -> None:
    result = release_control.gate_report(
        good_report(), require_recognition=True, expected_model="text-model"
    )
    assert result["status"] == "fail"
    assert "recognition engine" in result["errors"][0]


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.org/v1",
        "https://example.org/v1?token=x",
        "ftp://example.org/v1",
        "not-a-url",
    ],
)
def test_safe_endpoint_rejects_secrets_and_unsupported_urls(url: str) -> None:
    with pytest.raises(release_control.ReleaseControlError):
        release_control.safe_endpoint(url)


def test_preflight_records_optional_failure_but_passes(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    state = tmp_path / "state"
    staging = tmp_path / "staging"
    for path in (source, state, staging):
        path.mkdir()
    config = {
        "schema_version": 1,
        "profile": "tei-production",
        "capabilities": [
            {"id": "required", "required": True, "kind": "http", "url_env": "REQ"},
            {"id": "optional", "required": False, "kind": "http", "url_env": "OPT"},
        ],
        "storage": [
            {"id": "source", "path_env": "SOURCE", "writable": False},
            {"id": "state", "path_env": "STATE", "writable": True},
            {"id": "staging", "path_env": "STAGING", "writable": True},
        ],
        "schema": {"evidence": "1.0.0"},
    }

    def fake_check(capability, _environ):
        if capability["id"] == "optional":
            raise release_control.ReleaseControlError("optional unavailable")
        return {"id": "required", "required": True, "status": "available"}

    monkeypatch.setattr(release_control, "check_capability", fake_check)
    result = release_control.preflight(
        config,
        {
            "REQ": "https://required.test",
            "OPT": "https://optional.test",
            "SOURCE": str(source),
            "STATE": str(state),
            "STAGING": str(staging),
        },
    )
    assert result["status"] == "pass"
    assert result["capabilities"][1]["status"] == "unavailable"


def test_required_preflight_failure_blocks(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        release_control,
        "check_capability",
        lambda *_: (_ for _ in ()).throw(release_control.ReleaseControlError("down")),
    )
    result = release_control.preflight(
        {
            "schema_version": 1,
            "profile": "tei-production",
            "capabilities": [{"id": "required", "required": True, "kind": "http"}],
            "storage": [],
            "schema": {"evidence": "1.0.0"},
        },
        {},
    )
    assert result["status"] == "fail"
    assert result["errors"] == ["down"]


def manifest(commit: str) -> dict:
    return {"profile": "tei-production", "source": {"commit": commit, "dirty": False}}


def make_release(root: Path, commit: str) -> Path:
    release = root / "releases" / commit
    release.mkdir(parents=True)
    (release / "release-manifest.json").write_text(json.dumps(manifest(commit)))
    return release


def test_promotion_and_rollback_are_atomic_and_audited(tmp_path: Path) -> None:
    root = tmp_path / "root"
    first = make_release(root, "a" * 40)
    second = make_release(root, "b" * 40)
    history = root / "history.jsonl"

    promoted = promote_release.switch(root, first, history, "promote")
    rolled = promote_release.switch(root, second, history, "rollback")

    assert (root / "current").resolve() == second
    assert promoted["from"] is None
    assert rolled["from"] == str(first)
    events = [json.loads(line) for line in history.read_text().splitlines()]
    assert [event["action"] for event in events] == ["promote", "rollback"]
    assert all(len(event["manifest_sha256"]) == 64 for event in events)


def test_promotion_rejects_arbitrary_path_and_commit_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "release-manifest.json").write_text(json.dumps(manifest("a" * 40)))
    with pytest.raises(promote_release.PromotionError):
        promote_release.resolve_release(root, outside)

    mismatch = make_release(root, "a" * 40)
    (mismatch / "release-manifest.json").write_text(json.dumps(manifest("b" * 40)))
    with pytest.raises(promote_release.PromotionError, match="directory name"):
        promote_release.resolve_release(root, mismatch)


def test_manifest_secret_key_guard() -> None:
    with pytest.raises(release_control.ReleaseControlError, match="secret-like"):
        release_control.assert_no_secret_keys({"nested": {"api_token": "value"}})


def test_manifest_records_reproducibility_without_credentials(monkeypatch, tmp_path: Path) -> None:
    report = tmp_path / "run-report.json"
    report.write_text(json.dumps(good_report()))
    monkeypatch.setattr(
        release_control,
        "git_value",
        lambda *args: "" if args[0] == "status" else ("a" * 40 if args[-1] == "HEAD" else "b" * 40),
    )
    monkeypatch.setattr(release_control, "dependency_versions", lambda: {"example": "1.2.3"})
    monkeypatch.setenv("EXTRACTION_MODEL", "text-model")
    monkeypatch.setenv("QWEN3_VL_MODEL", "vision-model")
    monkeypatch.setenv("ORCHESTRATOR_MODEL", "orch-model")
    result = release_control.build_manifest(
        {
            "status": "pass",
            "profile": "tei-production",
            "schemas": {"evidence": "1.0.0"},
            "capabilities": [
                {
                    "id": "gpustack",
                    "status": "available",
                    "endpoint": "https://gpustack.example/v1",
                    "version": "1",
                    "models": ["text-model"],
                }
            ],
        },
        [report],
        "sha256:" + "c" * 64,
    )
    assert result["source"]["commit"] == "a" * 40
    assert result["dependencies"]["lock_sha256"]
    assert result["models"] == {
        "text": "text-model",
        "vision": "vision-model",
        "orchestrator": "orch-model",
    }
    assert "GPUSTACK_API_KEY" not in json.dumps(result)


def test_live_workflow_is_manual_inside_network_and_non_cancelling() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/tei-live-release.yml").read_text()
    trigger = workflow.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "schedule:" not in trigger
    assert "push:" not in trigger
    assert workflow.count("runs-on: [self-hosted, linux, outremer-tei]") == 3
    assert "environment: tei-staging" in workflow
    assert workflow.count("environment: tei-production") == 2
    assert "cancel-in-progress: false" in workflow
    assert "flock -n 9" in workflow
    assert "upload-artifact" not in workflow


def test_workflow_removes_transient_report_before_release_copy() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/tei-live-release.yml").read_text()
    cleanup = workflow.index("rm -f data/staging/run_report.json")
    copy = workflow.index("rsync -a --delete")
    assert cleanup < copy
