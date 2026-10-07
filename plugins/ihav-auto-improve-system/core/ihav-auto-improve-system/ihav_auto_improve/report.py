"""score.md, REPORT.md and CYCLE.md, rebuilt from the records only; judgments are never written here first."""

from __future__ import annotations

from pathlib import Path

from . import costs
from .compare import OK, counts, evidence, load
from .records import identity, read_jsonl, write_text_atomic

BUILT = "Built from the records by ihav-auto-improve-system; edits here are lost on the next rebuild."


def rebuild(pipeline, run_id: str = None) -> list:
    """Rebuild one run's files (or every run's) and the pipeline's CYCLE.md; return the paths written."""
    runs = [run_id] if run_id else run_ids(pipeline)
    written = []
    for rid in runs:
        written += write_run(load(pipeline, rid))
    write_text_atomic(pipeline.cycle, cycle_text(pipeline))
    return written + [pipeline.cycle]


def run_ids(pipeline) -> list:
    return sorted(p.name for p in pipeline.runs.iterdir() if (p / "run.json").is_file()) if pipeline.runs.is_dir() else []


def write_run(run: dict) -> list:
    paths = [run["dir"] / "score.md", run["dir"] / "REPORT.md"]
    write_text_atomic(paths[0], score_text(run))
    write_text_atomic(paths[1], report_text(run))
    return paths


def cell(found: dict) -> tuple:
    """Short table cells for one attempt: mandatory checks, graded values, reviews."""
    bad = [f"{n} {s.upper()}" + (f" ({r})" if r else "") for n, (s, r) in found["mandatory"].items() if s not in OK]
    total = len(found["mandatory"])
    mandatory = "; ".join(bad) if bad else (f"pass {total}/{total}" if total else "not run")
    graded = ", ".join(f"{n} {'-' if v is None else round(v, 3)}" for n, v in sorted(found["graded"].items())) or "-"
    reviews = ", ".join(f"{i}: {r[0] if r else 'pending'}" for i, r in found["reviews"].items()) or "-"
    return mandatory, graded, reviews


def score_text(run: dict) -> str:
    body = run["manifest"]
    n = counts(run["dir"])
    lines = [f"# Score: {body['run_id']}", "", BUILT, "",
             f"Pipeline `{body['pipeline']}` | tier `{body['tier']}` | profile `{body['profile']['sha256'][:12]}` | "
             f"cases `{body['case_set']['name']}` | repeats {body['repeats']} | status {body['status']}",
             f"Attempts: expected {n['expected']}, attempted {n['attempted']}, completed {n['completed']}, "
             f"failed {n['failed']}, missing {n['missing']}", "",
             "| Case | Kind | Mandatory checks | Graded | Agent review |", "|---|---|---|---|---|"]
    for attempt, found in evidence(run).items():
        lines.append(f"| {attempt} | {found['kind']} | " + " | ".join(cell(found)) + " |")
    return "\n".join(lines) + "\n"


def report_text(run: dict) -> str:
    body, found = run["manifest"], evidence(run)
    n = counts(run["dir"])
    profile = body["profile"]
    lines = [f"# Round report: {body['run_id']}", "", BUILT, "",
             f"- Pipeline `{body['pipeline']}`; adapter {body['adapter']['version']}; evaluator "
             f"{body['evaluator_version']}; tool {body['tool_version']}",
             f"- Status {body['status']}" + (f" ({body['reason']})" if body.get("reason") else "") +
             f"; created {body['created']}; closed {body.get('closed', '-')}",
             f"- Tier `{body['tier']}`" + (f"; admin approval: \"{body['approval']}\"" if body.get("approval") else ""),
             f"- Candidate identity `{body['identity']['sha256'][:16]}` ({len(body['identity']['files'])} files)"
             + ("" if body.get("identity_at_close", {}).get("sha256") in (None, body["identity"]["sha256"])
                else "; CHANGED during the run"),
             f"- Attempts: expected {n['expected']}, attempted {n['attempted']}, completed {n['completed']}, "
             f"failed {n['failed']}, missing {n['missing']}", "", "## Routes (model ids verbatim)", ""]
    lines += [f"- `{name}`: `{r['model']}` at {r['endpoint']}; credential {r.get('credential_env') or 'none'}"
              for name, r in sorted(profile["routes"].items())]
    lines += ["", "## Offline checks", ""]
    lines += [f"- `{' '.join(e['command'])}`: {e['status']}" + (f" ({e['reason']})" if e["reason"] else "")
              for e in run["evaluations"] if e["kind"] == "offline"] or ["- none declared"]
    lines += ["", "## Cost", "", "Unknown costs are listed apart and never counted as 0.", ""]
    for cls in ("e2e", "replay"):
        lines.append(f"- {cls}: " + costs.text(costs.summarize([r for r in run["invocations"] if r["class"] == cls])))
    lines += ["", "## Failures and gaps per case", ""]
    problems = [f"- {a}: {name} {s}" + (f": {r}" if r else "") for a, f in found.items()
                for name, (s, r) in f["mandatory"].items() if s not in OK]
    lines += problems or ["- none recorded"]
    pending = [f"- {a}: {item}" for a, f in found.items() for item, r in f["reviews"].items() if r is None]
    lines += ["", "## Pending agent reviews", ""] + (pending or ["- none"])
    lines += ["", "## Step replays", ""] + replay_lines(run)
    return "\n".join(lines) + "\n"


def replay_lines(run: dict) -> list:
    replays = [r for r in run["invocations"] if r["class"] == "replay"]
    if not replays:
        return ["- none"]
    checks = {}
    for e in run["evaluations"]:
        target = e.get("target") or {}
        if e["kind"] in ("check", "review") and "invocation" in target:
            label = e.get("name") or e.get("item")
            checks.setdefault((target["invocation"], target.get("variant")), {})[label] = e["status"] + (
                f" {round(e['score'], 3)}" if e.get("score") is not None else "")
    lines = ["| Invocation | Variant | Variant sha256 | Cost | Checks |", "|---|---|---|---|---|"]
    for r in replays:
        found = checks.get((r["id"], r["variant"]["name"]), {})
        cost = r["cost"]
        lines.append(f"| {r['id']} | {r['variant']['name']} | {r['variant']['sha256'][:12]} | "
                     f"{cost['value'] if cost['value'] is not None else cost['status']} | "
                     + ", ".join(f"{k} {v}" for k, v in sorted(found.items())) + " |")
    return lines


def cycle_text(pipeline) -> str:
    verdicts = read_jsonl(pipeline.verdicts)
    candidates = {v["candidate"] for v in verdicts}
    lines = [f"# Cycle: {pipeline.name}", "", BUILT, "Admin decisions are kept verbatim in decisions.md.", "",
             "## Runs", "", "| Run | Status | Tier | Cases | Expected/attempted/completed/failed/missing | Cost |",
             "|---|---|---|---|---|---|"]
    by_class = {"e2e": [], "replay": [], "finalist": []}
    for rid in run_ids(pipeline):
        run = load(pipeline, rid)
        body, n = run["manifest"], counts(run["dir"])
        for r in run["invocations"]:
            by_class["finalist" if r["class"] == "e2e" and rid in candidates else r["class"]].append(r)
        lines.append(f"| {rid} | {body['status']} | {body['tier']} | {body['case_set']['name']} | "
                     f"{n['expected']}/{n['attempted']}/{n['completed']}/{n['failed']}/{n['missing']} | "
                     f"{costs.text(costs.summarize(run['invocations']))} |")
    lines += ["", "## Verdicts", "", "| At | Baseline | Candidate | Verdict | Effect | Evidence still valid | Reasons |",
              "|---|---|---|---|---|---|---|"]
    for v in verdicts:
        reasons = v["not_comparable"] + v["failed"] + v["missing"]
        shown = "; ".join(reasons[:3]) + (f"; and {len(reasons) - 3} more" if len(reasons) > 3 else "")
        lines.append(f"| {v['at']} | {v['baseline']} | {v['candidate']} | {v['verdict']} | {v['effect'] or '-'} | "
                     f"{still_valid(pipeline, v)} | {shown or '-'} |")
    lines += ["", "A reject does not restore any file: the agent restores its own change and records it.",
              "An unchanged keep is a simplification or neutral change, not a quality improvement.",
              "", "## Cost by category", ""]
    lines += [f"- {cls}: {costs.text(costs.summarize(records))}" for cls, records in by_class.items()]
    return "\n".join(lines) + "\n"


def still_valid(pipeline, verdict: dict) -> str:
    body = load(pipeline, verdict["candidate"])["manifest"]
    current = identity(pipeline.project, body["identity_paths"], [pipeline.adapter])["sha256"]
    return "yes" if current == verdict["candidate_identity"] else "no (candidate files changed)"


def status_text(pipeline) -> str:
    runs = run_ids(pipeline)
    lines = [f"pipeline {pipeline.name} in {pipeline.dir}", f"runs: {len(runs)}"]
    if runs:
        run = load(pipeline, runs[-1])
        body, n = run["manifest"], counts(run["dir"])
        pending = sum(1 for f in evidence(run).values() for r in f["reviews"].values() if r is None)
        lines += [f"last run {runs[-1]}: {body['status']}, tier {body['tier']}, completed {n['completed']}/"
                  f"{n['expected']}, failed {n['failed']}, missing {n['missing']}, pending reviews {pending}",
                  f"report: {Path(run['dir']) / 'REPORT.md'}"]
    verdicts = read_jsonl(pipeline.verdicts)
    if verdicts:
        v = verdicts[-1]
        lines.append(f"last verdict: {v['verdict']} ({v['baseline']} -> {v['candidate']}), evidence still valid: "
                     f"{still_valid(pipeline, v)}")
    return "\n".join(lines)
