"""Seeded case generation and frozen case sets."""

from __future__ import annotations

import pytest

from ihav_auto_improve import Refused
from ihav_auto_improve.cases import generate, load_set, resolve, write_set

SCHEMA = {"type": "object", "required": ["size"], "properties": {
    "size": {"type": "integer", "minimum": 1, "maximum": 100},
    "mode": {"enum": ["fit", "fill"]},
    "image": {"type": "string", "format": "media"},
}}


def test_the_same_seed_gives_the_same_cases():
    first = generate(SCHEMA, 5, 42, False, ["inputs/a.png"])
    assert first == generate(SCHEMA, 5, 42, False, ["inputs/a.png"])
    assert first != generate(SCHEMA, 5, 43, False, ["inputs/a.png"])
    assert [c["id"] for c in first] == [f"random-{i:03d}" for i in range(1, 6)]


def test_hard_cases_cover_bounds_invalid_values_and_missing_required_fields():
    cases = generate(SCHEMA, 1, 1, True, ["inputs/a.png"])
    edges = [c["input"] for c in cases if c["kind"] == "edge"]
    invalid = [c["input"] for c in cases if c["kind"] == "invalid"]
    assert {e["size"] for e in edges} >= {1, 100}
    assert {e["mode"] for e in edges} >= {"fit", "fill"}
    assert any(i.get("size") == 0 for i in invalid) and any(i.get("size") == 101 for i in invalid)
    assert any("size" not in i for i in invalid)
    assert any(i.get("mode") == "not-an-option" for i in invalid)


def test_media_without_inputs_is_refused():
    with pytest.raises(Refused, match="inputs/ has no files"):
        generate(SCHEMA, 1, 1, False, [])


def test_case_sets_are_frozen_and_ids_checked(tmp_path):
    write_set(tmp_path, "s", [{"id": "a", "input": {}}], {})
    with pytest.raises(Refused, match="already exists"):
        write_set(tmp_path, "s", [], {})
    write_set(tmp_path, "dup", [{"id": "a", "input": {}}, {"id": "a", "input": {}}], {})
    with pytest.raises(Refused, match="unique ids"):
        load_set(tmp_path, "dup")


def test_case_identity_follows_the_media_bytes(tmp_path):
    (tmp_path / "inputs").mkdir()
    image = tmp_path / "inputs" / "a.png"
    image.write_bytes(b"one")
    case = {"id": "c", "input": {"size": 3, "image": "inputs/a.png"}}
    first = resolve(case, SCHEMA, tmp_path)
    image.write_bytes(b"two")
    assert resolve(case, SCHEMA, tmp_path)["identity"] != first["identity"]
    image.unlink()
    with pytest.raises(Refused, match="media .* is missing"):
        resolve(case, SCHEMA, tmp_path)
