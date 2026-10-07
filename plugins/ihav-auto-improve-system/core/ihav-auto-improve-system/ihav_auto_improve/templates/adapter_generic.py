"""Adapter for this project's pipeline, owned and edited by the project (ihav-auto-improve-system).

The runner calls each function in a fresh process of the project's interpreter (--python) with the project root
as the working directory. Every argument and return value is JSON. Fill in the TODOs; until then each call fails
with NotImplementedError and the run records the failure.

Rules the runner enforces:
- Send each model id exactly as the profile gives it (profile["routes"][route]["model"]); never strip a suffix.
- Report every model call, including retries and fallbacks (label "retry" or "fallback"), with its full
  rendered request envelope. A route that is not in the profile fails the run; there is no silent fallback.
- An unknown cost is {"value": None, "unit": None, "status": "pending" or "unavailable"}, never 0.
- Catch pipeline errors in run_e2e and return them in "error" together with the calls made so far.
"""

VERSION = "0.1.0"


def describe():
    return {
        "version": VERSION,
        "pipeline": "TODO-pipeline-name",
        "evaluator_version": "1",  # change when checks or rubric change: older runs stop being comparable
        "input_schema": {  # cases are generated from this (type, enum, minimum/maximum, format "media")
            "type": "object",
            "properties": {"message": {"type": "string", "examples": ["TODO a real user request"]}},
            "required": ["message"],
        },
        "modalities": ["text"],
        "steps": [  # every model call site; prompt/schema/fields are paths from the project root
            {"name": "TODO-step", "kind": "llm", "route": "TODO-route", "fallback": [], "needs": [],
             "replayable": True, "prompt": [], "schema": [], "fields": []},
        ],
        "mandatory_checks": [],  # names returned by checks_e2e that must pass
        "rubric": {"*": ["output matches the request"]},  # agent review items by case kind (or "*")
        "offline_checks": [],  # commands that never modify files, e.g. [["{python}", "-m", "pytest", "-q"]]
        "identity_paths": [],  # globs of source, config, prompt and schema files that define a candidate
    }


def run_e2e(case, out_dir, profile):
    """Run the whole pipeline on one case; write artifacts under out_dir.

    Return {"invocations": [{"turn", "step", "route", "model_requested", "model_actual", "envelope", "output",
    "usage", "generation_id", "cost": {"value", "unit", "status", "note"}, "label", "error"}],
    "artifacts": [{"path": relative to out_dir, "media_type"}], "output": ..., "error": None or text}.
    """
    raise NotImplementedError("TODO: call the project's pipeline here")


def run_step(invocation, variant, out_dir, profile):
    """Send one recorded call again with variant["content"] applied (prompt, schema or field descriptions).

    Return one invocation dict as in run_e2e (route, model_requested, envelope, output, cost, ...), plus optional
    "artifacts". Only called for steps with replayable True.
    """
    raise NotImplementedError("TODO: rebuild invocation['envelope'] with the variant and send it")


def checks_e2e(trace):
    """Return [{"name", "status": pass|fail|unscorable|not_applicable, "reason", "kind": mandatory|graded,
    "score": optional 0..1}] for one case; trace also has "case" and "out_dir"."""
    return []


def checks_step(result):
    """The same structure as checks_e2e, for one replayed call."""
    return []
