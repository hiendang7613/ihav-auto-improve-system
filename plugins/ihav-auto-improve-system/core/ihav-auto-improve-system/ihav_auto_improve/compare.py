"""Evidence per case attempt, the rules for a valid comparison (plan section 2) and the paired graded comparison."""

from __future__ import annotations

from pathlib import Path

from . import Refused
from .records import manifest, read_jsonl, rubric_items

OK = ("pass", "not_applicable")
CORE_CHECKS = ("completed", "artifacts", "invocation_contract", "profile_routes")
EPSILON = 1e-9


def load(pipeline, run_id: str) -> dict:
    run_dir = Path(pipeline.runs) / run_id
    if not run_dir.is_dir():
        raise Refused(f"no run {run_id} in {pipeline.runs}")
    return {"dir": run_dir, "manifest": manifest(run_dir), "invocations": read_jsonl(run_dir / "invocations.jsonl"),
            "evaluations": read_jsonl(run_dir / "evaluations.jsonl")}


def evidence(run: dict) -> dict:
    """attempt -> mandatory {name: (status, reason)}, graded {name: value}, reviews {item: (status, by) | None}.

    Later records of the same check or review replace earlier ones; all of them stay in the log.
    """
    body = run["manifest"]
    found = {a["attempt"]: {"case": a["case"], "kind": a["kind"], "mandatory": {}, "graded": {},
                            "reviews": {item: None for item in rubric_items(body, a["kind"])}}
             for a in body["attempts"]}
    for record in run["evaluations"]:
        entry = found.get((record.get("target") or {}).get("attempt"))
        if entry is None:
            continue
        if record["kind"] == "check" and record["class"] == "mandatory":
            entry["mandatory"][record["name"]] = (record["status"], record.get("reason") or "")
        elif record["kind"] == "check":
            entry["graded"][record["name"]] = graded_value(record)
        elif record["kind"] == "review":
            entry["reviews"][record["item"]] = (record["status"], record["by"])
    return found


def graded_value(record: dict):
    if record["status"] not in ("pass", "fail"):
        return None
    if record.get("score") is not None:
        return float(record["score"])
    return 1.0 if record["status"] == "pass" else 0.0


def counts(run_dir: Path) -> dict:
    """expected / attempted / completed / failed / missing, from the `completed` check of each attempt."""
    body = manifest(run_dir)
    done = {r["target"]["attempt"]: r["status"] for r in read_jsonl(Path(run_dir) / "evaluations.jsonl")
            if r["kind"] == "check" and r["name"] == "completed" and "attempt" in r["target"]}
    expected = len(body["attempts"])
    completed = sum(1 for status in done.values() if status == "pass")
    return {"expected": expected, "attempted": len(done), "completed": completed,
            "failed": len(done) - completed, "missing": expected - len(done)}


def comparability(base: dict, cand: dict) -> list:
    """Reasons the two runs cannot be compared; empty when the comparison is valid."""
    b, c = base["manifest"], cand["manifest"]
    reasons = [f"run {m['run_id']} is {m['status']}" + (f" ({m['reason']})" if m.get("reason") else "")
               for m in (b, c) if m["status"] != "finished"]
    if b["run_id"] == c["run_id"]:
        reasons.append("baseline and candidate are the same run")
    for key, label in (("pipeline", "pipeline"), ("contract_sha256", "mandatory contract"),
                       ("repeats", "declared repeats")):
        if b[key] != c[key]:
            reasons.append(f"{label} differs: {b[key]} vs {c[key]}")
    if b["evaluator_version"] != c["evaluator_version"]:
        reasons.append(f"evaluator version differs ({b['evaluator_version']} vs {c['evaluator_version']}): "
                       "run both versions again with one evaluator")
    if b["profile"]["sha256"] != c["profile"]["sha256"]:
        reasons.append(f"profile differs: {b['tier']} {b['profile']['sha256'][:12]} vs "
                       f"{c['tier']} {c['profile']['sha256'][:12]}")
    if {k: v["identity"] for k, v in b["cases"].items()} != {k: v["identity"] for k, v in c["cases"].items()}:
        reasons.append("case sets differ (ids, inputs or media): run both versions on the same cases")
    return reasons


def per_case(found: dict) -> dict:
    """case -> graded name -> mean over repeats; None when any repeat lacks a value (no lucky pick)."""
    values = {}
    for entry in found.values():
        for name, value in entry["graded"].items():
            values.setdefault(entry["case"], {}).setdefault(name, []).append(value)
    return {case: {name: None if None in vs else sum(vs) / len(vs) for name, vs in by.items()}
            for case, by in values.items()}


def graded_comparison(base: dict, cand: dict) -> dict:
    """Per graded check: totals over the cases both runs scored, and the cases the candidate left unscored."""
    b, c = per_case(evidence(base)), per_case(evidence(cand))
    names = sorted({n for by in b.values() for n in by} | {n for by in c.values() for n in by})
    result = {}
    for name in names:
        paired, missing = [], []
        for case, by in sorted(b.items()):
            old, new = by.get(name), c.get(case, {}).get(name)
            if old is not None and new is None:
                missing.append(case)
            elif old is not None:
                paired.append((old, new))
        base_total, cand_total = sum(p[0] for p in paired), sum(p[1] for p in paired)
        result[name] = {"cases": len(paired), "baseline": round(base_total, 6), "candidate": round(cand_total, 6),
                        "delta": round(cand_total - base_total, 6), "missing": missing}
    return result
