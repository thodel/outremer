"""#93: a bare given name never links by itself unless a person listed it."""

from linker import build_authority_lookup, is_bare_name, link_voyagers_to_outremer


def test_bare_forms_are_recognised():
    assert is_bare_name("Robert")
    assert is_bare_name("Robert II")
    assert is_bare_name("Heinrich III.")
    assert not is_bare_name("Robert of Milly")
    assert not is_bare_name("Radulfus Cadomensis")


def _index(provenance_for_bare):
    return {"persons": [{
        "authority_id": "AUTH:CR56", "preferred_label": "Robert of Milly",
        "variants": ["Robert", "Robert (Milly)", "Milly's Robert"],
        "normalized": {"preferred": "robert of milly", "variants": ["robert", "robert milly"]},
        "variant_provenance": {"Robert": provenance_for_bare},
    }]}


def test_mechanical_bare_variant_does_not_take_part():
    lookup = build_authority_lookup(_index([{"system": "omeka-xml", "locator": "person/item_1.xml"}]))
    assert "robert" not in lookup[0]["all_norms"]
    assert "robert milly" in lookup[0]["all_norms"]
    links = link_voyagers_to_outremer([{"name": "Robert"}], lookup)
    assert links[0]["status"] == "no_match", links[0]


def test_hand_copied_bare_variant_without_the_marker_does_not_take_part_either():
    """#45 copied the Omeka pattern into a hand-made record: still mechanical."""
    lookup = build_authority_lookup(_index([{"system": "github-issue", "locator": "issue:45"}]))
    assert "robert" not in lookup[0]["all_norms"]


def test_attested_bare_variant_links_at_full_confidence():
    lookup = build_authority_lookup(_index([{"system": "github-issue", "locator": "issue:92", "bare": "attested"}]))
    assert "robert" in lookup[0]["all_norms"]
    links = link_voyagers_to_outremer([{"name": "Robert"}], lookup)
    assert links[0]["top_candidate"]["outremer_id"] == "AUTH:CR56" and links[0]["status"] == "high"
