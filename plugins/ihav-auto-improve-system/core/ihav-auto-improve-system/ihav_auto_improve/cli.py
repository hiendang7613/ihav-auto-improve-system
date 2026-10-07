"""Command line: init, cases, round, evaluate, verify, report, status. --project is always explicit."""

from __future__ import annotations

import argparse
import subprocess
import sys

from . import Refused, __version__, report, workspace
from .adapter import Adapter, validate_describe
from .cases import generate, write_set
from .compare import evidence, load
from .records import add_review, manifest
from .rounds import run_round
from .verdict import decide


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="the project root that holds ./.ihav_space")
    common.add_argument("--pipeline", help="pipeline name (optional when the project has exactly one)")
    python = argparse.ArgumentParser(add_help=False)
    python.add_argument("--python", required=True, help="the project's interpreter, used to run its adapter")
    top = argparse.ArgumentParser(prog="ihav_auto_improve", description="Auto-improve loop for AI pipelines.")
    top.add_argument("--version", action="version", version=__version__)
    sub = top.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common, python], help="create the pipeline folder; never overwrites")
    init.add_argument("name")
    init.add_argument("--template", default="generic", choices=("generic", "ai-hub-sdk"))

    cases = sub.add_parser("cases", parents=[common, python], help="write a frozen, seeded case set")
    cases.add_argument("--n", type=int, required=True)
    cases.add_argument("--seed", type=int, required=True)
    cases.add_argument("--hard", action="store_true", help="add bounds, invalid inputs and earlier failures")
    cases.add_argument("--name", help="case set name (default seed<SEED>-n<N>[-hard])")

    rnd = sub.add_parser("round", parents=[common, python], help="offline checks, e2e pass, optional replays")
    rnd.add_argument("--cases", required=True, help="case set name in cases/")
    rnd.add_argument("--tier", required=True, help="cheap | standin | prod")
    rnd.add_argument("--steps", default="", help="comma-separated steps to replay with variants")
    rnd.add_argument("--variants", default="", help="comma-separated variant names (default: all of each step)")
    rnd.add_argument("--repeats", type=int, default=1)
    rnd.add_argument("--approval", help="the admin's words allowing a prod run, recorded verbatim")
    rnd.add_argument("--timeout", type=float, default=1800.0, help="seconds per adapter call")

    ev = sub.add_parser("evaluate", parents=[common], help="record one agent judgment")
    ev.add_argument("--run", required=True)
    target = ev.add_mutually_exclusive_group(required=True)
    target.add_argument("--case", help="case attempt id, e.g. random-001 or random-001@2")
    target.add_argument("--invocation", help="invocation id case/turn/step/n (with --variant for a replay)")
    ev.add_argument("--variant")
    ev.add_argument("--item", required=True, help="rubric item")
    ev.add_argument("--status", required=True, choices=("pass", "fail", "unscorable", "not_applicable"))
    ev.add_argument("--by", required=True, help="who judged")
    ev.add_argument("--note", default="")

    ver = sub.add_parser("verify", parents=[common], help="keep | reject | inconclusive for a candidate run")
    ver.add_argument("--baseline", required=True)
    ver.add_argument("--candidate", required=True)

    rep = sub.add_parser("report", parents=[common], help="rebuild score.md, REPORT.md and CYCLE.md")
    rep.add_argument("--run")
    sub.add_parser("status", parents=[common], help="short state of the pipeline")
    return top


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted; a running round is closed as aborted", file=sys.stderr)
        return 130


def cmd_init(args) -> int:
    try:
        version = subprocess.run([args.python, "-c", "import sys; print(sys.version.split()[0])"],
                                 capture_output=True, text=True, timeout=60).stdout.strip()
    except OSError as exc:
        raise Refused(f"--python {args.python} cannot be started: {exc}")
    if not version:
        raise Refused(f"--python {args.python} did not run")
    for path, state in workspace.init(args.project, args.name, args.template):
        print(f"{state}: {path}")
    print(f"python {version}: {args.python}")
    print("next: edit adapter.py and profiles.json, then run cases")
    return 0


def cmd_cases(args) -> int:
    pipeline = workspace.select(args.project, args.pipeline)
    describe = validate_describe(Adapter(pipeline, args.python, 600).call("describe"))
    media = sorted(f"inputs/{p.name}" for p in pipeline.inputs.iterdir() if p.is_file()) if pipeline.inputs.is_dir() else []
    cases = generate(describe["input_schema"], args.n, args.seed, args.hard, media,
                     regressions(pipeline) if args.hard else [])
    name = args.name or f"seed{args.seed}-n{args.n}" + ("-hard" if args.hard else "")
    path = write_set(pipeline.cases, name, cases, {"seed": args.seed, "n": args.n, "hard": args.hard})
    print(f"{len(cases)} cases: {path}")
    return 0


def regressions(pipeline) -> list:
    """Cases that failed a mandatory check or review in an earlier run ("errors already seen")."""
    found = []
    for rid in report.run_ids(pipeline):
        run = load(pipeline, rid)
        for attempt, entry in evidence(run).items():
            reviews = [r for r in entry["reviews"].values() if r]
            if any(s == "fail" for s, _ in entry["mandatory"].values()) or any(r[0] == "fail" for r in reviews):
                case = run["manifest"]["cases"][entry["case"]]
                found.append({"id": case["id"], "kind": case["kind"], "input": case["input"], "origin": f"{rid}/{attempt}"})
    return found


def cmd_round(args) -> int:
    pipeline = workspace.select(args.project, args.pipeline)
    split = lambda text: [x.strip() for x in text.split(",") if x.strip()]  # noqa: E731
    run_dir = run_round(pipeline, args.python, args.cases, args.tier, split(args.steps), split(args.variants),
                        args.repeats, args.approval, args.timeout)
    report.rebuild(pipeline, run_dir.name)
    body = manifest(run_dir)
    print(f"run {run_dir.name}: {body['status']}" + (f" ({body['reason']})" if body.get("reason") else ""))
    print(report.status_text(pipeline))
    return 0 if body["status"] == "finished" else 1


def cmd_evaluate(args) -> int:
    pipeline = workspace.select(args.project, args.pipeline)
    run_dir = pipeline.runs / args.run
    target = {"attempt": args.case} if args.case else {"invocation": args.invocation, "variant": args.variant}
    record = add_review(run_dir, target, args.item, args.status, args.by, args.note)
    report.rebuild(pipeline, args.run)
    print(f"recorded {record['item']} = {record['status']} for {args.case or args.invocation} in {args.run}")
    return 0


def cmd_verify(args) -> int:
    pipeline = workspace.select(args.project, args.pipeline)
    record = decide(pipeline, args.baseline, args.candidate)
    report.rebuild(pipeline, args.candidate)
    print(f"verdict: {record['verdict']}" + (f" ({record['effect']})" if record["effect"] else ""))
    for key in ("not_comparable", "failed", "missing"):
        for reason in record[key]:
            print(f"- {key}: {reason}")
    if record["verdict"] == "reject":
        print("reject does not restore files: restore your own change and record it")
    print(f"recorded in {pipeline.verdicts}")
    return 0


def cmd_report(args) -> int:
    pipeline = workspace.select(args.project, args.pipeline)
    for path in report.rebuild(pipeline, args.run):
        print(path)
    return 0


def cmd_status(args) -> int:
    print(report.status_text(workspace.select(args.project, args.pipeline)))
    return 0


COMMANDS = {"init": cmd_init, "cases": cmd_cases, "round": cmd_round, "evaluate": cmd_evaluate,
            "verify": cmd_verify, "report": cmd_report, "status": cmd_status}
