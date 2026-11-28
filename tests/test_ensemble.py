"""Offline tests for the ensemble recognition module (M16.1, #79).

Gateway and GPUStack are only reachable from the university network, so the
tests inject fakes shaped like the ``_pipeline`` bridges and assert on the
persisted pool, not on network.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

import config
from evaluation import ensemble

SCANS = Path(__file__).resolve().parent / "fixtures" / "scans"

PAGE = SCANS / "magna-carta-1215-incipit-page.pdf"  # 1230×820, page-shaped
STRIP = SCANS / "magna-carta-1215-incipit-hires.pdf"  # 4680×820, a line strip

# Disagreement scenario: every model reads differently, so only the dials
TEXTS = {
    "vlm": "aaa bbb ccc ddd eee fff ggg hhh",
    "kraken-catmus_medieval": "zzz yyy xxx www vvv uuu ttt sss",
    "kraken-model-b": "qqq ppp ooo nnn mmm lll kkk jjj",
    "kraken-model-c": "mmm nnn ooo ppp qqq rrr sss ttt",
    "trocr-essoins-middle-latin": "ddd eee fff ggg hhh iii jjj kkk",
    "trocr-model-b": "111 222 333 444 555 666 777 888",
    "trocr-model-c": "999 888 777 666 555 444 333 222",
}

AGREE = {m: "dominus vos duxit per desertum quadraginta annis" for m in TEXTS}

REGISTRY = [
    {"id": "kraken-catmus_medieval", "engine": "kraken", "zenodo_id": "10.5281/zenodo.7516057"},
    {"id": "kraken-model-b", "engine": "kraken", "zenodo_id": "z-k2"},
    {"id": "kraken-model-c", "engine": "kraken", "zenodo_id": "z-k3"},
    {"id": "trocr-essoins-middle-latin", "engine": "trocr", "hf_repo": "dh-unibe/trocr-essoins"},
    {"id": "trocr-model-b", "engine": "trocr", "hf_repo": "hf-t2"},
    {"id": "trocr-model-c", "engine": "trocr", "hf_repo": "hf-t3"},
]


@dataclass(frozen=True)
class _Result:
    text: str
    confidence: float
    model: str
    engine: str
    service_version: str = "0.1.0"


class _FakeAtr:
    def __init__(self, outcomes, registry=None):
        self.outcomes = outcomes
        self.registry = list(REGISTRY if registry is None else registry)
        self.calls: list[tuple[str, str]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_models(self):
        return list(self.registry)

    def transcribe(self, image, *, model, engine):
        self.calls.append((engine, model))
        outcome = self.outcomes[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(text=outcome, confidence=0.5, model=model, engine=engine)


class _Vlm:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def __call__(self, pdf):
        self.calls += 1
        return self.text, "qwen3-vl"


def _run(tmp_path, outcomes, **kwargs):
    vlm = _Vlm(outcomes.get("vlm", ""))
    client = _FakeAtr(outcomes)
    prov = ensemble.run_ensemble(PAGE, tmp_path / "out", vlm=vlm, client=client, **kwargs)
    return prov, client, vlm


def _spec(c):
    return c.get("spec", c["family"])


def _text_for(spec):
    return TEXTS[spec.split(":")[-1]]


def test_config_defaults():
    assert (config.ENSEMBLE_MIN_ENGINES, config.ENSEMBLE_MAX_LOOPS,
            config.ENSEMBLE_PER_ENGINE, config.ENSEMBLE_AGREEMENT_CER) == (3, 4, 3, 0.05)


def test_base_round_one_candidate_per_family(tmp_path):
    prov, client, vlm = _run(tmp_path, TEXTS, max_loops=0)
    assert client.calls == [("kraken", "kraken-catmus_medieval"), ("trocr", "trocr-essoins-middle-latin")]
    assert vlm.calls == 1
    assert [_spec(c) for c in prov["candidates"]] == [
        "vlm",
        "kraken:kraken-catmus_medieval",
        "trocr:trocr-essoins-middle-latin",
    ]
    assert prov["stopping"]["reason"] == "max_loops" and prov["loop_log"] == []
    for c in prov["candidates"]:
        assert c["round"] == 1 and c["seconds"] >= 0 and c["chars"] == len(_text_for(_spec(c)).strip())
        assert (tmp_path / "out" / c["file"]).read_text(encoding="utf-8") == c["text"]


def test_growth_stops_on_agreement(tmp_path):
    prov, client, _ = _run(tmp_path, AGREE)
    assert client.calls == [("kraken", "kraken-catmus_medieval"), ("trocr", "trocr-essoins-middle-latin")]
    assert prov["stopping"]["reason"] == "agreement"
    assert prov["stopping"]["disagreement"] == 0.0
    assert prov["loop_log"] == []


def test_growth_stops_at_max_loops_round_robin(tmp_path):
    prov, client, _ = _run(tmp_path, TEXTS, max_loops=4, per_engine=3)
    # Base round, then kraken and trocr alternate as the pools allow.
    # Base round, then kraken and trocr alternate as the pools allow.
    assert client.calls == [
        ("kraken", "kraken-catmus_medieval"), ("trocr", "trocr-essoins-middle-latin"),
        ("kraken", "kraken-model-b"), ("trocr", "trocr-model-b"),
        ("kraken", "kraken-model-c"), ("trocr", "trocr-model-c"),
    ]
    assert prov["stopping"]["reason"] == "max_loops"
    assert [e["added"] for e in prov["loop_log"]] == [
        "kraken:kraken-model-b", "trocr:trocr-model-b",
        "kraken:kraken-model-c", "trocr:trocr-model-c",
    ]
    assert all(e["disagreement_before"] > 0.05 for e in prov["loop_log"])
    assert len(prov["candidates"]) == 7  # base 3 + growth 4


def test_pool_depth_caps_candidates(tmp_path):
    prov, client, _ = _run(tmp_path, TEXTS, max_loops=4, per_engine=2)
    assert client.calls == [
        ("kraken", "kraken-catmus_medieval"), ("trocr", "trocr-essoins-middle-latin"),
        ("kraken", "kraken-model-b"), ("trocr", "trocr-model-b"),
    ]
    assert prov["stopping"]["reason"] == "pools_exhausted"
    assert len(prov["candidates"]) == 5


def test_failed_base_engine_recorded_and_family_grows(tmp_path):
    outcomes = {**TEXTS, "kraken-catmus_medieval": RuntimeError("gateway 502")}
    prov, client, _ = _run(tmp_path, outcomes, max_loops=4)
    assert client.calls == [
        ("kraken", "kraken-catmus_medieval"), ("trocr", "trocr-essoins-middle-latin"),
        ("kraken", "kraken-model-b"), ("trocr", "trocr-model-b"),
        ("kraken", "kraken-model-c"), ("trocr", "trocr-model-c"),
    ]
    failed = [c for c in prov["candidates"] if c.get("error")]
    assert len(failed) == 1 and "file" not in failed[0]
    assert failed[0]["spec"] == "kraken:kraken-catmus_medieval"
    assert "502" in failed[0]["error"]
    assert any(_spec(c) == "kraken:kraken-model-b" and c["round"] == 2 for c in prov["candidates"])
    assert prov["stopping"]["reason"] == "max_loops"


def test_agreement_threshold_is_a_dial(tmp_path):
    prov, client, _ = _run(tmp_path, TEXTS, agree_cer=2.0)
    assert client.calls == [("kraken", "kraken-catmus_medieval"), ("trocr", "trocr-essoins-middle-latin")]
    assert prov["stopping"]["reason"] == "agreement"
    assert prov["policy"]["agreement_cer"] == 2.0


def test_min_engines_limits_base_families(tmp_path):
    prov, client, _ = _run(tmp_path, TEXTS, min_engines=2, max_loops=1)
    assert [_spec(c) for c in prov["candidates"] if c["round"] == 1] == \
        ["vlm", "kraken:kraken-catmus_medieval"]
    assert [_spec(c) for c in prov["candidates"] if c["round"] == 2] == ["kraken:kraken-model-b"]


@pytest.mark.parametrize("bad", [0, 4])
def test_bad_min_engines_refused(tmp_path, bad):
    with pytest.raises(ValueError, match="min_engines"):
        _run(tmp_path, TEXTS, min_engines=bad)


def test_build_pools_curated_first_registry_fills(tmp_path):
    client = _FakeAtr({})
    pools = ensemble.build_pools(client, per_engine=3)
    assert pools == {
        "kraken": ["kraken-catmus_medieval", "kraken-model-b", "kraken-model-c"],
        "trocr": ["trocr-essoins-middle-latin", "trocr-model-b", "trocr-model-c"],
    }
    shallow = ensemble.build_pools(client, per_engine=2)
    assert shallow == {f: p[:2] for f, p in pools.items()}
    # A curated id the registry does not carry is dropped, not an error.
    ghost = ensemble.build_pools(client,
                                 model_order={"kraken": ("ghost", "kraken-model-b"),
                                              "trocr": ("trocr-model-c",)},
                                 per_engine=3)
    assert ghost["kraken"] == ["kraken-model-b", "kraken-catmus_medieval", "kraken-model-c"]
    assert ghost["trocr"] == ["trocr-model-c", "trocr-essoins-middle-latin", "trocr-model-b"]


def test_output_is_competing_claims_never_asserted_text(tmp_path):
    prov, _, _ = _run(tmp_path, AGREE, max_loops=1)
    persisted = json.loads((tmp_path / "out" / "provenance.json").read_text(encoding="utf-8"))
    assert persisted == prov
    assert prov["status"] == "competing_claims"
    for key in ("text", "transcript", "fused", "assertion", "ground_truth", "gold"):
        assert key not in prov, f"asserted-text key {key!r} in the pool"
    for c in prov["candidates"]:
        assert {"family", "round", "spec", "engine", "model", "backend", "seconds", "chars"} <= set(c)
    kraken = next(c for c in prov["candidates"] if _spec(c) == "kraken:kraken-catmus_medieval")
    assert kraken["backend"] == "atr-gateway"
    assert kraken["weights"] == {"zenodo_id": "10.5281/zenodo.7516057"}
    assert kraken["service_version"] == "0.1.0"
    vlm_c = next(c for c in prov["candidates"] if _spec(c) == "vlm")
    assert vlm_c["backend"] == "gpustack"


def test_strip_refused_with_gateway_families(tmp_path):
    vlm = _Vlm("x")
    client = _FakeAtr(TEXTS)
    with pytest.raises(ValueError, match="a strip, not a page"):
        ensemble.run_ensemble(STRIP, tmp_path / "out", vlm=vlm, client=client)
    assert vlm.calls == 0
    assert client.calls == []


def test_strip_allowed_for_vlm_alone(tmp_path):
    prov, client, vlm = _run(tmp_path, TEXTS, min_engines=1, max_loops=2)
    assert vlm.calls == 1
    assert client.calls == []
    assert [_spec(c) for c in prov["candidates"]] == ["vlm"]
    assert prov["stopping"]["reason"] == "insufficient_candidates"
