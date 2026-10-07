"""One round (plan section 3): offline checks, the e2e pass on a frozen case set, then optional step replays."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import TOOL, Refused, __version__, artifacts
from .adapter import CHECK_STATUSES, Adapter, AdapterFailed, step_paths, validate_describe
from .cases import load_set, resolve as resolve_case
from .compare import CORE_CHECKS, counts
from .costs import normalize
from .profile import invocation_problems, resolve as resolve_profile
from .records import (add_evaluation, append_invocation, close_run, create_run, identity, now, read_json,
                      read_jsonl, sha256_file, sha256_json)


def run_round(pipeline, python: str, case_set: str, tier: str, steps=(), variant_names=(), repeats: int = 1,
              approval: str = None, timeout: float = 1800.0) -> Path:
    """Check everything that can be refused, then run; the run folder is closed even when interrupted."""
    adapter = Adapter(pipeline, python, timeout)
    describe = validate_describe(adapter.call("describe"))
    if not pipeline.profiles.is_file():
        raise Refused(f"{pipeline.profiles} is missing")
    profile = resolve_profile(read_json(pipeline.profiles), describe, tier, approval)
    if repeats < 1:
        raise Refused("--repeats must be 1 or more")
    case_body = load_set(pipeline.cases, case_set)
    cases = {c["id"]: resolve_case(c, describe["input_schema"], pipeline.dir) for c in case_body["cases"]}
    variants = load_variants(pipeline, describe, steps, variant_names)
    patterns = describe["identity_paths"] + step_paths(describe)
    attempts = [{"attempt": case_id if repeats == 1 else f"{case_id}@{k}", "case": case_id, "repeat": k,
                 "kind": case["kind"]} for case_id, case in cases.items() for k in range(1, repeats + 1)]
    run_dir = create_run(pipeline.runs, {
        "tool": TOOL, "tool_version": __version__, "pipeline": pipeline.name, "python": python, "timeout": timeout,
        "adapter": {"version": describe["version"], "describe": describe, "describe_sha256": sha256_json(describe)},
        "evaluator_version": describe["evaluator_version"],
        "contract_sha256": sha256_json({"core": CORE_CHECKS, "mandatory": sorted(describe["mandatory_checks"]),
                                        "rubric": describe["rubric"]}),
        "tier": tier, "profile": profile, "approval": approval,
        "case_set": {"name": case_body["name"], "sha256": sha256_json({k: c["identity"] for k, c in cases.items()})},
        "cases": cases, "repeats": repeats, "attempts": attempts,
        "replay": {"steps": list(steps), "variants": variants},
        "identity_paths": patterns, "identity": identity(pipeline.project, patterns, [pipeline.adapter]),
    })
    status, reason = "finished", None
    try:
        if not run_offline_checks(pipeline, run_dir, describe, python, patterns, timeout):
            status, reason = "aborted", "offline checks failed; no model was called"
        else:
            for attempt in attempts:
                run_attempt(adapter, run_dir, attempt, cases[attempt["case"]], describe, profile)
            for step in steps:
                replay_step(adapter, run_dir, describe, profile, step, variants[step])
    except BaseException:
        status, reason = "aborted", "interrupted or stopped by an error in the runner"
        raise
    finally:
        close_run(run_dir, status, reason=reason, counts=counts(run_dir),
                  identity_at_close=identity(pipeline.project, patterns, [pipeline.adapter]))
    return run_dir


def load_variants(pipeline, describe: dict, steps, names) -> dict:
    """Variant files variants/<step>/<name>.json; their content and hash go into the records."""
    by_name = {s["name"]: s for s in describe["steps"]}
    if names and not steps:
        raise Refused("--variants needs --steps")
    found = {}
    for step in steps:
        if step not in by_name:
            raise Refused(f"step {step!r} is not in describe(): {', '.join(by_name)}")
        if not by_name[step]["replayable"]:
            raise Refused(f"step {step} is replayable: false; it is never replayed and no estimate replaces it. "
                          "Apply the change and run an e2e round instead")
        files = sorted((pipeline.variants / step).glob("*.json"))
        missing = set(names) - {f.stem for f in files}
        if missing:
            raise Refused(f"no variant {', '.join(sorted(missing))} in {pipeline.variants / step}")
        chosen = [f for f in files if not names or f.stem in names]
        if not chosen:
            raise Refused(f"no variants in {pipeline.variants / step}")
        found[step] = [{"name": f.stem, "sha256": sha256_file(f), "content": read_json(f)} for f in chosen]
    return found


def run_offline_checks(pipeline, run_dir: Path, describe: dict, python: str, patterns: list, timeout: float) -> bool:
    """Run the adapter's offline commands; one that fails or changes a candidate file fails."""
    passed = True
    for argv in describe["offline_checks"]:
        command = [python if part == "{python}" else part for part in argv]
        before = identity(pipeline.project, patterns, [pipeline.adapter])
        try:
            done = subprocess.run(command, cwd=pipeline.project, capture_output=True, text=True, timeout=timeout)
            code, output = done.returncode, done.stdout + done.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, output = None, str(exc)
        after = identity(pipeline.project, patterns, [pipeline.adapter])
        changed = sorted(k for k in set(before["files"]) | set(after["files"])
                         if before["files"].get(k) != after["files"].get(k))
        status = "pass" if code == 0 and not changed else "fail"
        reason = f"changed {', '.join(changed)}" if changed else ("" if code == 0 else f"exit {code}")
        add_evaluation(run_dir, {"kind": "offline", "command": command, "exit_code": code, "status": status,
                                 "reason": reason, "output_tail": output[-2000:], "identity": before["sha256"]})
        passed = passed and status == "pass"
    return passed


def run_attempt(adapter: Adapter, run_dir: Path, attempt: dict, case: dict, describe: dict, profile: dict) -> None:
    out = run_dir / attempt["attempt"]
    out.mkdir()
    target = {"attempt": attempt["attempt"]}
    case_arg = {"id": case["id"], "kind": case["kind"], "repeat": attempt["repeat"], "input": case["input"],
                "media": {key: m["path"] for key, m in case["media"].items()}}
    try:
        trace = adapter.call("run_e2e", case_arg, str(out), profile, log=out / "adapter.log")
        if not isinstance(trace, dict):
            raise AdapterFailed("error", "run_e2e must return a JSON object")
    except AdapterFailed as exc:
        add_check(run_dir, target, "completed", "fail", f"{exc.kind}: {exc}")
        return
    (out / "trace.json").write_text(json.dumps(trace, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    calls = trace.get("invocations") if isinstance(trace.get("invocations"), list) else None
    counter, contract, routes = {}, [] if calls is not None else ["trace.invocations must be a list"], []
    for item in calls or []:
        if not isinstance(item, dict):
            contract.append("an invocation entry is not an object")
            continue
        key = (item.get("turn", 1), item.get("step"))
        counter[key] = counter.get(key, 0) + 1
        base = {"id": f"{attempt['attempt']}/{key[0]}/{key[1]}/{counter[key]}", "class": "e2e",
                "attempt": attempt["attempt"], "turn": key[0], "step": key[1], "n": counter[key]}
        found = record_call(run_dir, base, item, describe, profile)
        contract += found[0]
        routes += found[1]
    finish_checks(run_dir, target, out, trace.get("error"), contract, routes, trace.get("artifacts"))
    if not trace.get("error"):
        run_adapter_checks(adapter, run_dir, target, "checks_e2e", {**trace, "case": case_arg, "out_dir": str(out)},
                           describe, out)


def replay_step(adapter: Adapter, run_dir: Path, describe: dict, profile: dict, step: str, variants: list) -> None:
    """Replay each recorded e2e call of one step with each variant (the small per-step pass)."""
    originals = [r for r in read_jsonl(run_dir / "invocations.jsonl")
                 if r["class"] == "e2e" and r["step"] == step and not r.get("error")]
    for original in originals:
        for variant in variants:
            out = run_dir / "replay" / step / variant["name"] / re.sub(r"[^A-Za-z0-9_.@-]", "_", original["id"])
            out.mkdir(parents=True)
            target = {"invocation": original["id"], "variant": variant["name"]}
            try:
                result = adapter.call("run_step", original, variant, str(out), profile, log=out / "adapter.log")
                if not isinstance(result, dict):
                    raise AdapterFailed("error", "run_step must return a JSON object")
            except AdapterFailed as exc:
                add_check(run_dir, target, "completed", "fail", f"{exc.kind}: {exc}")
                continue
            base = {key: original[key] for key in ("id", "attempt", "turn", "step", "n")}
            base.update({"class": "replay", "replay_of": original["id"], "variant": variant})
            contract, routes = record_call(run_dir, base, result, describe, profile)
            finish_checks(run_dir, target, out, result.get("error"), contract, routes, result.get("artifacts"))
            if not result.get("error"):
                run_adapter_checks(adapter, run_dir, target, "checks_step", {**result, "out_dir": str(out)},
                                   describe, out)


def record_call(run_dir: Path, base: dict, item: dict, describe: dict, profile: dict) -> tuple:
    """Append one model call with its rendered request envelope and hash; return contract and route problems."""
    envelope = item.get("envelope")
    record = {**base, "route": item.get("route"), "model_requested": item.get("model_requested"),
              "model_actual": item.get("model_actual"), "label": item.get("label"), "envelope": envelope,
              "envelope_sha256": sha256_json(envelope), "output": item.get("output"), "usage": item.get("usage"),
              "generation_id": item.get("generation_id"), "cost": normalize(item.get("cost")),
              "error": item.get("error"), "at": now()}
    append_invocation(run_dir, record)
    step = next((s for s in describe["steps"] if s["name"] == record["step"]), None)
    contract = []
    if step is None:
        contract.append(f"{record['id']}: step {record['step']!r} is not in describe()")
    if not isinstance(record["turn"], int) or record["turn"] < 1:
        contract.append(f"{record['id']}: turn must be a whole number from 1")
    if not isinstance(envelope, dict) or not envelope:
        contract.append(f"{record['id']}: the rendered request envelope is missing")
    if record["label"] not in (None, "retry", "fallback"):
        contract.append(f"{record['id']}: label must be retry, fallback or null")
    return contract, invocation_problems(record, step, profile) if step else []


def finish_checks(run_dir: Path, target: dict, out: Path, error, contract: list, routes: list, listed) -> None:
    """The core's own mandatory checks for one e2e attempt or one replay."""
    add_check(run_dir, target, "completed", "fail" if error else "pass", str(error or ""))
    add_check(run_dir, target, "invocation_contract", "fail" if contract else "pass", "; ".join(contract))
    add_check(run_dir, target, "profile_routes", "fail" if routes else "pass", "; ".join(routes))
    listed = [] if listed is None else listed
    results = [artifacts.check(out, a) for a in listed] if isinstance(listed, list) else [("fail", "artifacts must be a list")]
    status = next((s for s in ("fail", "unscorable") if any(r[0] == s for r in results)),
                  "pass" if results else "not_applicable")
    add_check(run_dir, target, "artifacts", status, "; ".join(r[1] for r in results if r[1]) or
              ("" if results else "no artifacts listed"))


def run_adapter_checks(adapter: Adapter, run_dir: Path, target: dict, method: str, payload: dict, describe: dict,
                       out: Path) -> None:
    """Record the adapter's checks; a declared mandatory check it did not return is unscorable, never passed."""
    declared = describe["mandatory_checks"]
    required = declared if method == "checks_e2e" else [method]
    try:
        results = adapter.call(method, payload, log=out / "adapter.log")
        if not isinstance(results, list):
            raise AdapterFailed("error", f"{method} must return a list")
    except AdapterFailed as exc:
        for name in required:
            add_check(run_dir, target, name, "unscorable", f"{method} failed: {exc}", source="adapter")
        return
    returned = set()
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("name"), str):
            continue
        name, status = result["name"], result.get("status")
        returned.add(name)
        mandatory = name in declared or result.get("kind") == "mandatory"
        reason = str(result.get("reason") or "")
        if status not in CHECK_STATUSES:
            status, reason = "unscorable", f"adapter returned status {status!r}"
        score = result.get("score")
        score = score if isinstance(score, (int, float)) and not isinstance(score, bool) else None
        add_check(run_dir, target, name, status, reason, source="adapter",
                  kind="mandatory" if mandatory else "graded", score=score)
    for name in required:
        if name not in returned and method == "checks_e2e":
            add_check(run_dir, target, name, "unscorable", f"{method} did not return this check", source="adapter")


def add_check(run_dir: Path, target: dict, name: str, status: str, reason: str, source: str = "core",
              kind: str = "mandatory", score=None) -> None:
    add_evaluation(run_dir, {"kind": "check", "source": source, "target": target, "name": name, "class": kind,
                             "status": status, "reason": reason, "score": score})
