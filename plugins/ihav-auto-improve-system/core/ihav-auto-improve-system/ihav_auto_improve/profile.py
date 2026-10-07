"""The execution profile: every route a step may call, resolved for one tier before anything runs."""

from __future__ import annotations

import re

from . import Refused
from .records import sha256_json

TIERS = ("cheap", "standin", "prod")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def resolve(profiles: dict, describe: dict, tier: str, approval: str = None) -> dict:
    """Freeze the routes of one tier, or refuse before running when any route is unmapped or unfit.

    There is no default and no fallback to another tier: a cheap run never reaches a prod route.
    """
    if tier not in TIERS:
        raise Refused(f"--tier must be one of {', '.join(TIERS)}")
    if tier == "prod" and not (approval or "").strip():
        raise Refused("the prod tier runs only when asked for explicitly: give --approval with the admin's words")
    table = ((profiles.get("tiers") or {}).get(tier) or {}).get("routes") or {}
    problems, used = [], {}
    for step in describe["steps"]:
        for route in [step["route"], *step["fallback"]]:
            entry = table.get(route)
            if not isinstance(entry, dict):
                problems.append(f"step {step['name']} ({step['kind']}): route {route!r} has no {tier} mapping")
                continue
            problems += route_problems(step, route, entry)
            used[route] = entry
        allowed = (table.get(step["route"]) or {}).get("fallback") or []
        problems += [f"step {step['name']}: fallback {fb!r} is not allowed by route {step['route']!r} in {tier}"
                     for fb in step["fallback"] if fb not in allowed]
    if problems:
        raise Refused(f"profile {tier} refused before running:\n- " + "\n- ".join(problems))
    frozen = {"tier": tier, "routes": used}
    return {**frozen, "approval": approval, "sha256": sha256_json(frozen)}


def route_problems(step: dict, route: str, entry: dict) -> list:
    where = f"{route} ({step['name']})"
    problems = [f"{where}: {key} is missing" for key in ("endpoint", "model") if not isinstance(entry.get(key), str)]
    if "credential_env" not in entry:
        problems.append(f"{where}: credential_env must name the variable (or be null), never hold the key")
    elif entry["credential_env"] is not None and not ENV_NAME.match(str(entry["credential_env"])):
        problems.append(f"{where}: credential_env must be a variable name such as OPENROUTER_API_KEY")
    missing = set(step["needs"]) - set(entry.get("capabilities") or [])
    if missing:
        problems.append(f"{where}: model lacks {', '.join(sorted(missing))}")
    return problems


def invocation_problems(record: dict, step: dict, profile: dict) -> list:
    """An invocation must use its step's route or an allowed fallback, with the model id sent verbatim."""
    route = record.get("route")
    if route not in [step["route"], *step["fallback"]]:
        return [f"{record['id']}: route {route!r} is not a route of step {step['name']} in this profile"]
    expected = profile["routes"][route]["model"]
    if record.get("model_requested") != expected:
        return [f"{record['id']}: sent model {record.get('model_requested')!r}, profile has {expected!r} (verbatim)"]
    return []
