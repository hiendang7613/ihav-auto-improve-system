"""Fake adapter for tests: no model, no network, no SDK. Copied over a pipeline's adapter.py by the tests.

Behaviour comes from files in the project root, which are part of the candidate identity:
- prompts/plan.txt: the "prompt"; its words set the graded quality ("concise" up, "verbose" down).
- fake.json: switches for failure states (crash, bad_artifact, sleep, route, strip_suffix, cost_pending,
  offline_checks, evaluator_version, omit_mandatory).
"""

import json
import struct
import time
import zlib
from pathlib import Path


def config():
    path = Path("fake.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def quality(prompt):
    return round(0.5 + 0.4 * ("concise" in prompt) - 0.3 * ("verbose" in prompt), 3)


def png_bytes():
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + \
        chunk(b"IEND", b"")


def describe():
    cfg = config()
    return {
        "version": "fake-1",
        "pipeline": "demo",
        "evaluator_version": cfg.get("evaluator_version", "1"),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "examples": ["menu", "poster", "card"]},
                "size": {"type": "integer", "minimum": 1, "maximum": 100},
                "image": {"type": "string", "format": "media"},
            },
            "required": ["text", "size"],
        },
        "modalities": ["text", "image"],
        "steps": [
            {"name": "plan", "kind": "llm", "route": "llm_main", "fallback": ["llm_backup"],
             "needs": ["structured_output"], "replayable": True, "prompt": "prompts/plan.txt"},
            {"name": "draw", "kind": "image", "route": "image_main", "replayable": False},
        ],
        "mandatory_checks": ["output_present"],
        "rubric": {"*": ["looks_right"], "invalid": ["refusal_clear"]},
        "offline_checks": cfg.get("offline_checks", [["{python}", "-c", "pass"]]),
        "identity_paths": ["prompts/*.txt", "fake.json"],
    }


def call(step, route, model, envelope, output, cost):
    return {"turn": 1, "step": step, "route": route, "model_requested": model, "model_actual": model,
            "envelope": envelope, "output": output, "usage": {"input_tokens": 10, "output_tokens": 5},
            "generation_id": f"gen-{step}", "cost": cost, "label": None, "error": None}


def run_e2e(case, out_dir, profile):
    cfg = config()
    if cfg.get("sleep"):
        time.sleep(cfg["sleep"])
    if case["id"] in cfg.get("crash", []):
        raise RuntimeError("fake pipeline crashed")
    prompt = Path("prompts/plan.txt").read_text(encoding="utf-8")
    route = cfg.get("route", "llm_main")
    model = (profile["routes"].get(route) or {}).get("model", "unmapped/model")
    if cfg.get("strip_suffix"):
        model = model.split(":")[0]
    cost = {"value": None, "unit": None, "status": "pending"} if cfg.get("cost_pending") else \
        {"value": 0.0002, "unit": "USD", "status": "reported"}
    envelope = {"system": "You plan layouts.", "prompt": prompt, "input": case["input"], "model": model}
    calls = [call("plan", route, model, envelope, {"quality": quality(prompt)}, cost)]
    size = case["input"].get("size")
    if "text" not in case["input"] or not isinstance(size, int) or not 1 <= size <= 100:
        return {"invocations": calls, "artifacts": [], "output": {"refused": "invalid input"}, "error": None}
    out = Path(out_dir) / "final.png"
    out.write_bytes(b"not a png" if case["id"] in cfg.get("bad_artifact", []) else png_bytes())
    image_model = profile["routes"]["image_main"]["model"]
    calls.append(call("draw", "image_main", image_model, {"prompt": f"draw {case['input']['text']}"}, {"file": "final.png"},
                      {"value": None, "unit": None, "status": "unavailable",
                       "note": "stand-in: no per-call fee, uses subscription quota"}))
    return {"invocations": calls, "artifacts": [{"path": "final.png", "media_type": "image/png"}],
            "output": {"quality": quality(prompt)}, "error": None}


def run_step(invocation, variant, out_dir, profile):
    prompt = variant["content"]["prompt"]
    envelope = {**invocation["envelope"], "prompt": prompt}
    return {"route": invocation["route"], "model_requested": profile["routes"][invocation["route"]]["model"],
            "model_actual": profile["routes"][invocation["route"]]["model"], "envelope": envelope,
            "output": {"quality": quality(prompt)},
            "cost": {"value": 0.0001, "unit": "USD", "status": "estimated"}}


def checks_e2e(trace):
    if config().get("omit_mandatory"):
        return []
    refused = (trace.get("output") or {}).get("refused")
    present = bool(trace.get("artifacts")) or bool(refused)
    return [
        {"name": "output_present", "kind": "mandatory", "status": "pass" if present else "fail",
         "reason": "" if present else "no image and no refusal"},
        {"name": "quality", "kind": "graded", "status": "not_applicable" if refused else "pass",
         "score": None if refused else trace["output"]["quality"], "reason": "refusal" if refused else ""},
    ]


def checks_step(result):
    return [{"name": "quality", "kind": "graded", "status": "pass", "score": result["output"]["quality"]}]
