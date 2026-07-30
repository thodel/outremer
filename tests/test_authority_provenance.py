import json
from pathlib import Path

from scripts.backfill_authority_provenance import backfill, validate

ROOT = Path(__file__).resolve().parents[1]


def test_all_authority_name_forms_have_attributed_provenance():
    data = json.loads(
        (ROOT / "scripts" / "outremer_index.json").read_text(encoding="utf-8")
    )
    assert not validate(data)
    assert len(data["persons"]) == 129
    assert all(record["variant_provenance"] for record in data["persons"])


def test_manual_record_provenance_resolves_to_governing_issue():
    fixture = {
        "persons": [
            {
                "authority_id": "AUTH:T1",
                "preferred_label": "Example",
                "variants": ["Exemplum"],
                "provenance": {
                    "source_system": "manual",
                    "source_files": [],
                    "note": "added per issue #45",
                },
            }
        ]
    }
    backfill(fixture)
    sources = fixture["persons"][0]["variant_provenance"]["Exemplum"]
    assert sources == [{"system": "github-issue", "locator": "issue:45"}]
