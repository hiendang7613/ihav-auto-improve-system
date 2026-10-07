"""The project-owned adapter: its description contract and the subprocess bridge that calls it."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path

from . import Refused
from .records import now

HOST = Path(__file__).resolve().parents[1] / "scripts" / "adapter_host.py"
STEP_KINDS = ("llm", "image", "video", "audio")
CHECK_STATUSES = ("pass", "fail", "unscorable", "not_applicable")
DESCRIBE_DEFAULTS = {"modalities": [], "mandatory_checks": [], "rubric": {}, "offline_checks": [], "identity_paths": []}
STEP_DEFAULTS = {"fallback": [], "needs": [], "prompt": [], "schema": [], "fields": []}


class AdapterFailed(Exception):
    """An adapter call raised, returned nothing or ran out of time; `kind` is error or timeout."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class Adapter:
    def __init__(self, pipeline, python: str, timeout: float):
        self.pipeline = pipeline
        self.python = python
        self.timeout = timeout

    def call(self, method: str, *args, log: Path = None):
        """Run one method in a fresh process of the project's interpreter and return its JSON result."""
        with tempfile.TemporaryDirectory(prefix="ihav-aim-") as tmp:
            request, response = Path(tmp) / "request.json", Path(tmp) / "response.json"
            request.write_text(json.dumps({"method": method, "args": list(args)}, ensure_ascii=False), encoding="utf-8")
            log = log or Path(tmp) / "log.txt"
            command = [self.python, str(HOST), str(self.pipeline.project), str(self.pipeline.adapter),
                       str(request), str(response)]
            with open(log, "a", encoding="utf-8") as out:
                out.write(f"--- {now()} {method}\n")
                out.flush()
                try:
                    proc = subprocess.Popen(command, cwd=self.pipeline.project, stdout=out, stderr=subprocess.STDOUT,
                                            start_new_session=os.name == "posix")
                except OSError as exc:
                    raise Refused(f"--python {self.python} cannot be started: {exc}")
                try:
                    code = proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    stop(proc)
                    raise AdapterFailed("timeout", f"{method} ran past {self.timeout} s; its processes were stopped")
                except BaseException:
                    stop(proc)
                    raise
            if not response.is_file():
                raise AdapterFailed("error", f"{method} exited {code} without a result: {tail(log)}")
            reply = json.loads(response.read_text(encoding="utf-8"))
        if not reply["ok"]:
            error = reply["error"]
            raise AdapterFailed("error", f"{method} raised {error['type']}: {error['message']}\n{error['traceback'][-1500:]}")
        return reply["result"]


def stop(proc: subprocess.Popen) -> None:
    """Stop the whole process group (the adapter may start its own children) and reap it."""
    if os.name != "posix":
        proc.kill()
        proc.wait()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=5)
            break
        except subprocess.TimeoutExpired:
            continue
    proc.wait()


def tail(path: Path, size: int = 1500) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).exists() else ""
    return text[-size:]


def as_list(value) -> list:
    return [value] if isinstance(value, str) else list(value or [])


def validate_describe(raw) -> dict:
    """Check the adapter's description and fill defaults; refuse with every problem listed."""
    if not isinstance(raw, dict):
        raise Refused("describe() must return a JSON object")
    body = {**DESCRIBE_DEFAULTS, **raw}
    problems = []
    for key, kind in (("version", str), ("pipeline", str), ("evaluator_version", str), ("input_schema", dict),
                      ("steps", list), ("mandatory_checks", list), ("rubric", dict), ("offline_checks", list),
                      ("identity_paths", list), ("modalities", list)):
        if not isinstance(body.get(key), kind):
            problems.append(f"{key} must be a {kind.__name__}")
    steps, seen = [], set()
    for raw_step in body["steps"] if isinstance(body.get("steps"), list) else []:
        step = {**STEP_DEFAULTS, **raw_step} if isinstance(raw_step, dict) else {}
        name = step.get("name")
        if not isinstance(name, str) or not name or name in seen or "/" in name:
            problems.append(f"step name {name!r} must be unique, non-empty and without '/'")
            continue
        seen.add(name)
        if step.get("kind") not in STEP_KINDS:
            problems.append(f"step {name}: kind must be one of {', '.join(STEP_KINDS)}")
        if not isinstance(step.get("route"), str):
            problems.append(f"step {name}: route must name a profile route")
        if not isinstance(step.get("replayable"), bool):
            problems.append(f"step {name}: replayable must be true or false")
        for key in ("fallback", "needs", "prompt", "schema", "fields"):
            step[key] = as_list(step[key])
        steps.append(step)
    if not steps:
        problems.append("steps must list at least one model step")
    if any(not isinstance(c, list) or not c or not all(isinstance(a, str) for a in c) for c in body["offline_checks"]):
        problems.append("offline_checks must be a list of argument lists, e.g. [[\"{python}\", \"-m\", \"pytest\"]]")
    if problems:
        raise Refused("adapter describe() is not valid:\n- " + "\n- ".join(problems))
    body["steps"] = steps
    return body


def step_paths(describe: dict) -> list:
    """Prompt, schema and field-description files of every step: part of the candidate's identity."""
    return [p for step in describe["steps"] for key in ("prompt", "schema", "fields") for p in step[key]]
