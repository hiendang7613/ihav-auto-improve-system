"""The verdict keep | reject | inconclusive (plan section 2), bound to the candidate's identity."""

from __future__ import annotations

from . import __version__
from .compare import CORE_CHECKS, EPSILON, OK, comparability, evidence, graded_comparison, load
from .records import append_jsonl, identity, now


def decide(pipeline, baseline: str, candidate: str) -> dict:
    """Compare two recorded runs and append the verdict to verdicts.jsonl; nothing is run or restored."""
    base, cand = load(pipeline, baseline), load(pipeline, candidate)
    body = cand["manifest"]
    current = identity(pipeline.project, body["identity_paths"], [pipeline.adapter])
    blocked = comparability(base, cand) + identity_problems(body, current)
    failed, missing, graded = [], [], {}
    if not blocked:
        failed, missing = candidate_problems(cand)
        graded = graded_comparison(base, cand)
        for name, g in graded.items():
            if g["missing"]:
                missing.append(f"graded {name}: no candidate value for {', '.join(g['missing'])}")
            if g["delta"] < -EPSILON:
                failed.append(f"graded {name} is worse than the baseline: {g['baseline']} -> {g['candidate']} "
                              f"over {g['cases']} paired case(s)")
    verdict = "inconclusive" if blocked else "reject" if failed else "inconclusive" if missing else "keep"
    record = {
        "at": now(), "tool_version": __version__, "baseline": baseline, "candidate": candidate, "verdict": verdict,
        "comparable": not blocked, "not_comparable": blocked, "failed": failed, "missing": missing,
        "graded": graded, "effect": effect(verdict, graded), "candidate_identity": body["identity"]["sha256"],
        "baseline_identity": base["manifest"]["identity"]["sha256"], "profile": body["profile"]["sha256"],
    }
    append_jsonl(pipeline.verdicts, record)
    return record


def identity_problems(body: dict, current: dict) -> list:
    problems = []
    if body.get("identity_at_close", {}).get("sha256") != body["identity"]["sha256"]:
        problems.append("candidate files changed during its own run")
    if current["sha256"] != body["identity"]["sha256"]:
        changed = sorted(k for k in set(current["files"]) | set(body["identity"]["files"])
                         if current["files"].get(k) != body["identity"]["files"].get(k))
        problems.append(f"candidate changed since its run ({', '.join(changed) or 'patterns'}); its evidence no "
                        "longer applies: run the e2e round again")
    return problems


def candidate_problems(cand: dict) -> tuple:
    """Failures and missing evidence of the candidate itself: offline checks, mandatory checks, reviews."""
    describe = cand["manifest"]["adapter"]["describe"]
    failed, missing = [], []
    offline = [e for e in cand["evaluations"] if e["kind"] == "offline"]
    if len(offline) < len(describe["offline_checks"]):
        missing.append("offline checks were not all run")
    failed += [f"offline check {' '.join(e['command'])} failed: {e['reason']}" for e in offline if e["status"] != "pass"]
    for attempt, entry in evidence(cand).items():
        names = list(CORE_CHECKS) + [n for n in describe["mandatory_checks"] if n not in CORE_CHECKS]
        names += [n for n in entry["mandatory"] if n not in names]
        for name in names:
            status, reason = entry["mandatory"].get(name, (None, "not recorded"))
            if status == "fail":
                failed.append(f"{attempt}: {name} failed: {reason}")
            elif status not in OK:
                missing.append(f"{attempt}: {name} is {status or 'missing'}: {reason}")
        for item, review in entry["reviews"].items():
            if review is None:
                missing.append(f"{attempt}: agent review {item} is pending")
            elif review[0] == "fail":
                failed.append(f"{attempt}: agent review {item} failed (by {review[1]})")
            elif review[0] not in OK:
                missing.append(f"{attempt}: agent review {item} is {review[0]}")
    return failed, missing


def effect(verdict: str, graded: dict):
    if verdict != "keep":
        return None
    return "improved" if any(g["delta"] > EPSILON for g in graded.values()) else "unchanged"
