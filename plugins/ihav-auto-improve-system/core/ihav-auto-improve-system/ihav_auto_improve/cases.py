"""Case sets: seeded cases from the adapter's input schema, frozen in cases/<name>.json.

Supported schema subset: an object whose properties have `enum`, or `type` integer | number | string | boolean
with minimum/maximum, minLength/maxLength and `examples`; `"format": "media"` picks a file from inputs/.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

from . import Refused
from .records import now, sha256_file, sha256_json, write_new

def generate(schema: dict, n: int, seed: int, hard: bool, media: list, regressions: list = ()) -> list:
    """n random cases; with `hard`, also each property at its bounds, one invalid value each, and earlier failures."""
    rnd = random.Random(seed)
    props, required = schema.get("properties") or {}, schema.get("required") or []
    cases = [_case("random", i, {k: _value(s, rnd, media) for k, s in props.items()}) for i in range(1, n + 1)]
    if hard:
        edges, invalids = [], []
        for key, spec in props.items():
            for value in _edges(spec):
                edges.append({**{k: _value(s, rnd, media) for k, s in props.items()}, key: value})
            for value in _invalids(spec):
                invalids.append({**{k: _value(s, rnd, media) for k, s in props.items()}, key: value})
            if key in required:
                invalids.append({k: _value(s, rnd, media) for k, s in props.items() if k != key})
        cases += [_case("edge", i, v) for i, v in enumerate(edges, 1)]
        cases += [_case("invalid", i, v) for i, v in enumerate(invalids, 1)]
        seen = {sha256_json(c["input"]) for c in cases}
        for old in regressions:
            if sha256_json(old["input"]) not in seen:
                seen.add(sha256_json(old["input"]))
                cases.append({"id": "regression-" + old["id"].replace("regression-", ""), "kind": old["kind"],
                              "input": old["input"], "origin": old["origin"]})
    return cases


def _case(kind: str, index: int, value: dict) -> dict:
    return {"id": f"{kind}-{index:03d}", "kind": kind, "input": value}


def _value(spec: dict, rnd: random.Random, media: list):
    if "enum" in spec:
        return rnd.choice(spec["enum"])
    if spec.get("format") == "media":
        if not media:
            raise Refused("the schema asks for media but inputs/ has no files")
        return rnd.choice(media)
    kind = spec.get("type")
    low = spec.get("minimum", 0)
    high = spec.get("maximum", low + 100)
    if kind == "integer":
        return rnd.randint(low, high)
    if kind == "number":
        return round(rnd.uniform(low, high), 4)
    if kind == "boolean":
        return rnd.random() < 0.5
    if kind == "string":
        if spec.get("examples"):
            return rnd.choice(spec["examples"])
        size = rnd.randint(spec.get("minLength", 1), spec.get("maxLength", 12))
        return "".join(rnd.choice(string.ascii_lowercase) for _ in range(size))
    raise Refused(f"schema type {kind!r} is not supported by case generation; write the case set by hand")


def _edges(spec: dict) -> list:
    if "enum" in spec:
        return list(spec["enum"])
    kind = spec.get("type")
    if kind in ("integer", "number"):
        return [spec[k] for k in ("minimum", "maximum") if k in spec]
    if kind == "string" and spec.get("format") != "media":
        return ["x" * spec[k] for k in ("minLength", "maxLength") if k in spec]
    return [True, False] if kind == "boolean" else []


def _invalids(spec: dict) -> list:
    if "enum" in spec:
        return ["not-an-option"]
    kind = spec.get("type")
    if kind in ("integer", "number"):
        return ([spec["minimum"] - 1] if "minimum" in spec else []) + ([spec["maximum"] + 1] if "maximum" in spec else [])
    if kind == "string" and spec.get("minLength", 0) > 0:
        return ["x" * (spec["minLength"] - 1)]
    return []


def write_set(directory: Path, name: str, cases: list, meta: dict) -> Path:
    path = Path(directory) / f"{name}.json"
    body = {"name": name, "created": now(), **meta, "cases": cases}
    if not write_new(path, json.dumps(body, indent=1, ensure_ascii=False) + "\n"):
        raise Refused(f"case set {path} already exists; case sets are frozen, choose another --name")
    return path


def load_set(directory: Path, name: str) -> dict:
    path = Path(directory) / (name if name.endswith(".json") else f"{name}.json")
    if not path.is_file():
        raise Refused(f"no case set {path}")
    body = json.loads(path.read_text(encoding="utf-8"))
    ids = [c.get("id") for c in body.get("cases") or []]
    if not ids or len(set(ids)) != len(ids) or not all(isinstance(i, str) and i and "/" not in i and "@" not in i for i in ids):
        raise Refused(f"{path}: cases need unique ids without '/' or '@'")
    return body


def resolve(case: dict, schema: dict, pipeline_dir: Path) -> dict:
    """Attach absolute media paths and the case identity (input plus media bytes)."""
    media = {}
    for key, spec in (schema.get("properties") or {}).items():
        if spec.get("format") == "media" and key in case["input"]:
            path = (Path(pipeline_dir) / case["input"][key]).resolve()
            if not path.is_file():
                raise Refused(f"case {case['id']}: media {path} is missing")
            media[key] = {"path": str(path), "sha256": sha256_file(path)}
    identity = sha256_json({"input": case["input"], "media": {k: v["sha256"] for k, v in media.items()}})
    return {"id": case["id"], "kind": case.get("kind", "random"), "input": case["input"], "media": media,
            "identity": identity}
