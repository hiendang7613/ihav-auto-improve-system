"""The full path init -> cases -> round -> evaluate -> verify -> report/status, with the fake adapter."""

from __future__ import annotations

import json
import time

from conftest import CHEAP, route
from ihav_auto_improve.records import sha256_file, sha256_json


def test_init_never_overwrites_and_refuses_the_m4_template(project, capsys):
    adapter = project.dir / "adapter.py"
    before = adapter.read_text(encoding="utf-8")
    assert project.cli("init", "demo") == 0
    assert "kept: " in capsys.readouterr().out
    assert adapter.read_text(encoding="utf-8") == before
    assert project.cli("init", "other", "--template", "ai-hub-sdk") == 2
    assert not (project.dir.parent / "other").exists()


def test_full_cycle_keeps_a_better_candidate_and_writes_the_records(project):
    base = project.baseline()
    project.set_prompt("Plan the layout. Be concise.")
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert (verdict["verdict"], verdict["effect"]) == ("keep", "improved")
    assert verdict["candidate_identity"] == project.manifest(cand)["identity"]["sha256"]

    body = project.manifest(cand)
    assert body["status"] == "finished"
    assert body["counts"] == {"expected": 2, "attempted": 2, "completed": 2, "failed": 0, "missing": 0}
    assert body["profile"]["routes"]["llm_main"]["model"] == "vendor/demo:free"
    calls = project.records(cand, "invocations.jsonl")
    assert [c["id"] for c in calls] == ["random-001/1/plan/1", "random-001/1/draw/1",
                                        "random-002/1/plan/1", "random-002/1/draw/1"]
    assert all(c["envelope_sha256"] == sha256_json(c["envelope"]) for c in calls)
    assert calls[0]["model_requested"] == "vendor/demo:free"
    for name in ("score.md", "REPORT.md", "run.json", "evaluations.jsonl"):
        assert (project.dir / "runs" / cand / name).is_file()
    assert "| keep | improved |" in (project.dir / "CYCLE.md").read_text(encoding="utf-8")


def test_a_candidate_with_no_measured_change_is_kept_as_unchanged(project):
    base = project.baseline()
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert (verdict["verdict"], verdict["effect"]) == ("keep", "unchanged")


def test_a_pending_agent_review_is_inconclusive(project):
    base = project.baseline()
    cand = project.round()
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "inconclusive"
    assert "random-001: agent review looks_right is pending" in verdict["missing"]


def test_a_failed_agent_review_on_one_case_rejects(project):
    base = project.baseline()
    cand = project.round()
    project.review_all(cand, status="fail", only="random-002")
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "reject"
    assert verdict["failed"] == ["random-002: agent review looks_right failed (by test-agent)"]


def test_a_crash_on_one_case_rejects_even_when_totals_improve(project):
    base = project.baseline()
    project.set_prompt("Plan. Be concise.")
    project.set_fake(crash=["random-002"])
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "reject"
    assert any(r.startswith("random-002: completed failed: error: run_e2e raised RuntimeError") for r in verdict["failed"])
    assert project.manifest(cand)["counts"]["failed"] == 1


def test_an_undecodable_artifact_rejects(project):
    base = project.baseline()
    project.set_fake(bad_artifact=["random-001"])
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "reject"
    assert any("random-001: artifacts failed: final.png does not decode as image/png" in r for r in verdict["failed"])


def test_a_declared_mandatory_check_that_is_not_returned_is_never_a_pass(project):
    base = project.baseline()
    project.set_fake(omit_mandatory=True)
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "inconclusive"
    assert any("output_present is unscorable" in r for r in verdict["missing"])


def test_a_worse_graded_score_rejects(project):
    base = project.baseline()
    project.set_prompt("Plan the layout, verbose.")
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "reject"
    assert verdict["failed"] == ["graded quality is worse than the baseline: 1.0 -> 0.4 over 2 paired case(s)"]


def test_evidence_is_void_once_the_candidate_changes(project, capsys):
    base = project.baseline()
    cand = project.round()
    project.review_all(cand)
    project.set_prompt("Plan the layout. Edited after the run.")
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "inconclusive" and not verdict["comparable"]
    assert any("candidate changed since its run (prompts/plan.txt)" in r for r in verdict["not_comparable"])
    assert project.cli("status") == 0
    assert "evidence still valid: no" in capsys.readouterr().out


def test_runs_on_different_case_sets_are_not_compared(project):
    base = project.baseline()
    assert project.cli("cases", "--n", "2", "--seed", "8", "--name", "other") == 0
    cand = project.round(cases="other")
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "inconclusive"
    assert any("case sets differ" in r for r in verdict["not_comparable"])


def test_changed_media_bytes_change_the_case_identity(project):
    base = project.baseline()
    same = project.round()
    image = project.dir / "inputs" / "one.png"
    image.write_bytes(image.read_bytes() + b"\x00")
    changed = project.round()
    for run in (same, changed):
        project.review_all(run)
    assert project.verify(base, same)["comparable"]
    assert any("case sets differ" in r for r in project.verify(base, changed)["not_comparable"])


def test_evaluator_profile_and_repeat_changes_are_not_compared(project):
    base = project.baseline()
    project.set_fake(evaluator_version="2")
    other_evaluator = project.round()
    project.set_fake()
    project.set_routes("cheap", {**CHEAP, "image_main": route("vendor/image-v2", ["image"])})
    other_profile = project.round()
    project.set_routes("cheap", CHEAP)
    repeated = project.round("--repeats", "2")
    reasons = {run: " ".join(project.verify(base, run)["not_comparable"])
               for run in (other_evaluator, other_profile, repeated)}
    assert "evaluator version differs (1 vs 2)" in reasons[other_evaluator]
    assert "profile differs" in reasons[other_profile]
    assert "declared repeats differs: 1 vs 2" in reasons[repeated]
    ids = [c["id"] for c in project.records(repeated, "invocations.jsonl")]
    assert "random-001@2/1/plan/1" in ids


def test_an_unmapped_route_is_refused_before_anything_runs(project, capsys):
    project.set_routes("cheap", {k: v for k, v in CHEAP.items() if k != "image_main"})
    assert project.cli("round", "--cases", "base", "--tier", "cheap") == 2
    assert "step draw (image): route 'image_main' has no cheap mapping" in capsys.readouterr().err
    assert project.runs() == []


def test_the_prod_tier_runs_only_with_recorded_approval(project, capsys):
    project.set_routes("prod", CHEAP)
    assert project.cli("round", "--cases", "base", "--tier", "prod") == 2
    assert "--approval" in capsys.readouterr().err
    words = "admin 2026-10-07: ok, one prod run for these 2 cases"
    assert project.cli("round", "--cases", "base", "--tier", "prod", "--approval", words) == 0
    assert project.manifest(project.runs()[-1])["approval"] == words


def test_a_model_id_that_is_not_sent_verbatim_rejects(project):
    base = project.baseline()
    project.set_fake(strip_suffix=True)
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "reject"
    assert any("sent model 'vendor/demo', profile has 'vendor/demo:free' (verbatim)" in r for r in verdict["failed"])


def test_a_call_on_a_route_outside_the_profile_fails_the_case(project):
    base = project.baseline()
    project.set_fake(route="prod_llm")
    cand = project.round()
    project.review_all(cand)
    verdict = project.verify(base, cand)
    assert verdict["verdict"] == "reject"
    assert any("route 'prod_llm' is not a route of step plan" in r for r in verdict["failed"])


def test_failing_offline_checks_stop_the_round_before_any_model_call(project):
    base = project.baseline()
    project.set_fake(offline_checks=[["{python}", "-c", "import sys; sys.exit(3)"]])
    cand = project.round(expect=1)
    body = project.manifest(cand)
    assert (body["status"], body["reason"]) == ("aborted", "offline checks failed; no model was called")
    assert project.records(cand, "invocations.jsonl") == []
    assert body["counts"]["missing"] == 2
    assert any("is aborted" in r for r in project.verify(base, cand)["not_comparable"])


def test_an_offline_check_that_changes_a_candidate_file_fails(project):
    script = "open('prompts/plan.txt', 'a').write(' fixed')"
    project.set_fake(offline_checks=[["{python}", "-c", script]])
    run = project.round(expect=1)
    offline = [e for e in project.records(run, "evaluations.jsonl") if e["kind"] == "offline"]
    assert (offline[0]["status"], offline[0]["reason"]) == ("fail", "changed prompts/plan.txt")


def test_a_slow_adapter_is_stopped_at_the_timeout(project):
    project.set_fake(sleep=30)
    started = time.monotonic()
    run = project.round("--timeout", "1")
    assert time.monotonic() - started < 20
    completed = [e for e in project.records(run, "evaluations.jsonl") if e.get("name") == "completed"]
    assert [e["status"] for e in completed] == ["fail", "fail"]
    assert completed[0]["reason"].startswith("timeout: run_e2e ran past 1.0 s")


def test_step_replays_record_variant_content_and_hash(project):
    project.add_variant("plan", "concise", {"prompt": "Plan. Be concise."})
    project.add_variant("plan", "verbose", {"prompt": "Plan, verbose."})
    run = project.round("--steps", "plan", "--variants", "concise")
    replays = [c for c in project.records(run, "invocations.jsonl") if c["class"] == "replay"]
    assert [(r["id"], r["variant"]["name"]) for r in replays] == [("random-001/1/plan/1", "concise"),
                                                                  ("random-002/1/plan/1", "concise")]
    variant = project.dir / "variants" / "plan" / "concise.json"
    assert replays[0]["variant"]["sha256"] == sha256_file(variant)
    assert replays[0]["variant"]["content"] == {"prompt": "Plan. Be concise."}
    assert replays[0]["envelope"]["prompt"] == "Plan. Be concise."
    graded = [e for e in project.records(run, "evaluations.jsonl")
              if e.get("name") == "quality" and "invocation" in e["target"]]
    assert [e["score"] for e in graded] == [0.9, 0.9]


def test_a_step_that_is_not_replayable_is_refused(project, capsys):
    project.add_variant("draw", "bright", {"prompt": "bright"})
    assert project.cli("round", "--cases", "base", "--tier", "cheap", "--steps", "draw") == 2
    assert "replayable: false" in capsys.readouterr().err
    assert project.runs() == []


def test_an_unknown_cost_is_recorded_as_unknown_never_zero(project):
    project.set_fake(cost_pending=True)
    run = project.round()
    costs = [c["cost"] for c in project.records(run, "invocations.jsonl")]
    assert {(c["status"], c["value"]) for c in costs} == {("pending", None), ("unavailable", None)}
    report = (project.dir / "runs" / run / "REPORT.md").read_text(encoding="utf-8")
    assert "- e2e: 4 call(s): 4 call(s) cost unknown (2 pending, 2 unavailable)" in report


def test_evaluate_refuses_unknown_targets(project):
    run = project.round()
    assert project.cli("evaluate", "--run", run, "--case", "nope", "--item", "looks_right", "--status", "pass",
                       "--by", "a") == 2
    assert project.cli("evaluate", "--run", run, "--case", "random-001", "--item", "typo", "--status", "pass",
                       "--by", "a") == 2
    assert project.cli("evaluate", "--run", run, "--invocation", "random-001/1/plan/9", "--item", "x",
                       "--status", "pass", "--by", "a") == 2


def test_markdown_is_rebuilt_from_the_records(project):
    run = project.baseline()
    score = project.dir / "runs" / run / "score.md"
    before = score.read_text(encoding="utf-8")
    assert "looks_right: pass" in before
    score.write_text("edited by hand", encoding="utf-8")
    assert project.cli("report") == 0
    assert score.read_text(encoding="utf-8") == before


def test_hard_cases_add_bounds_invalid_inputs_and_earlier_failures(project):
    project.set_fake(crash=["random-001"])
    project.round()
    assert project.cli("cases", "--n", "1", "--seed", "3", "--hard", "--name", "hard") == 0
    body = json.loads((project.dir / "cases" / "hard.json").read_text(encoding="utf-8"))
    kinds = [c["kind"] for c in body["cases"]]
    assert {"random", "edge", "invalid"} <= set(kinds)
    regression = [c for c in body["cases"] if c["id"].startswith("regression-")]
    assert [c["id"] for c in regression] == ["regression-random-001"]
    assert regression[0]["origin"].endswith("/random-001")
    assert project.cli("cases", "--n", "1", "--seed", "3", "--name", "hard") == 2  # frozen


def test_invalid_input_cases_need_no_artifact(project):
    project.set_fake()
    assert project.cli("cases", "--n", "1", "--seed", "3", "--hard", "--name", "hard") == 0
    run = project.round(cases="hard")
    evaluations = project.records(run, "evaluations.jsonl")
    invalid = {e["target"]["attempt"]: e["status"] for e in evaluations
               if e.get("name") in ("artifacts", "output_present") and e["target"].get("attempt", "").startswith("invalid")}
    assert invalid and set(invalid.values()) <= {"pass", "not_applicable"}


def test_a_run_is_not_compared_with_itself(project):
    run = project.baseline()
    assert "baseline and candidate are the same run" in project.verify(run, run)["not_comparable"]


def test_pipeline_selection_is_explicit_when_there_are_several(project, capsys):
    assert project.cli("init", "second") == 0
    assert project.cli("status") == 2
    assert "choose a pipeline with --pipeline" in capsys.readouterr().err
    assert project.cli("status", "--pipeline", "demo") == 0
