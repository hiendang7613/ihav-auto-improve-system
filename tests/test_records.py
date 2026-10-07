"""Record contract: unique runs, a manifest closed once, append-only logs, costs, identity."""

from __future__ import annotations

import pytest

from ihav_auto_improve import Refused, costs
from ihav_auto_improve.records import (append_invocation, append_jsonl, close_run, create_run, identity, read_jsonl,
                                       write_new)


def test_run_ids_are_unique_and_folders_never_reused(tmp_path):
    runs = [create_run(tmp_path, {"attempts": []}) for _ in range(30)]
    assert len({r.name for r in runs}) == 30
    assert all((r / "run.json").is_file() for r in runs)


def test_a_closed_manifest_is_never_rewritten_and_takes_no_more_invocations(tmp_path):
    run = create_run(tmp_path, {"attempts": []})
    append_invocation(run, {"id": "a/1/s/1"})
    close_run(run, "finished", counts={})
    with pytest.raises(Refused):
        close_run(run, "aborted")
    with pytest.raises(Refused):
        append_invocation(run, {"id": "a/1/s/2"})
    assert len(read_jsonl(run / "invocations.jsonl")) == 1


def test_write_new_never_overwrites(tmp_path):
    path = tmp_path / "x.txt"
    assert write_new(path, "first")
    assert not write_new(path, "second")
    assert path.read_text() == "first"


def test_jsonl_is_append_only_and_a_corrupt_line_is_refused(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"a": 2})
    assert [r["a"] for r in read_jsonl(path)] == [1, 2]
    with open(path, "a") as handle:
        handle.write("{broken\n")
    with pytest.raises(Refused, match="log.jsonl:3"):
        read_jsonl(path)


@pytest.mark.parametrize("raw, expected", [
    ({"value": 0.01, "unit": "USD", "status": "reported"}, (0.01, "reported")),
    ({"value": 0.02, "unit": "USD", "status": "estimated"}, (0.02, "estimated")),
    ({"value": 0, "unit": None, "status": "pending"}, (None, "pending")),
    ({"value": None, "unit": "USD", "status": "reported"}, (None, "unavailable")),
    ({"value": True, "unit": "USD", "status": "reported"}, (None, "unavailable")),
    ({"value": 1}, (None, "unavailable")),
    (None, (None, "unavailable")),
])
def test_cost_normalization_never_turns_unknown_into_zero(raw, expected):
    cost = costs.normalize(raw)
    assert (cost["value"], cost["status"]) == expected


def test_cost_summary_keeps_units_apart_and_counts_unknown_costs():
    records = [{"cost": costs.normalize(c)} for c in (
        {"value": 0.25, "unit": "USD", "status": "reported"}, {"value": 2, "unit": "credits", "status": "reported"},
        {"value": 0.5, "unit": "USD", "status": "estimated"}, {"status": "pending"}, None)]
    summary = costs.summarize(records)
    assert summary["known"] == {"USD": {"reported": 0.25, "estimated": 0.5}, "credits": {"reported": 2}}
    assert summary["unknown"] == {"pending": 1, "unavailable": 1}
    assert costs.text(summary).endswith("2 call(s) cost unknown (1 pending, 1 unavailable)")


def test_identity_covers_patterns_and_the_adapter_but_not_runtime_folders(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1")
    space = tmp_path / ".ihav_space" / "t" / "demo"
    space.mkdir(parents=True)
    (space / "adapter.py").write_text("pass")
    (space / "trace.py").write_text("ignored")
    first = identity(tmp_path, ["**/*.py"], [space / "adapter.py"])
    assert set(first["files"]) == {"src/app.py", ".ihav_space/t/demo/adapter.py"}
    (tmp_path / "src" / "app.py").write_text("x = 2")
    assert identity(tmp_path, ["**/*.py"], [space / "adapter.py"])["sha256"] != first["sha256"]
