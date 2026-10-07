"""The execution profile is resolved before running and never reaches another tier."""

from __future__ import annotations

import pytest

from conftest import CHEAP, route
from ihav_auto_improve import Refused
from ihav_auto_improve.adapter import validate_describe
from ihav_auto_improve.profile import resolve

DESCRIBE = validate_describe({
    "version": "1", "pipeline": "p", "evaluator_version": "1", "input_schema": {},
    "steps": [{"name": "plan", "kind": "llm", "route": "llm_main", "fallback": ["llm_backup"],
               "needs": ["structured_output"], "replayable": True},
              {"name": "draw", "kind": "image", "route": "image_main", "replayable": False}],
})


def profiles(tier="cheap", routes=CHEAP):
    return {"tiers": {tier: {"routes": routes}}}


def test_a_complete_mapping_is_frozen_with_a_hash():
    frozen = resolve(profiles(), DESCRIBE, "cheap")
    assert set(frozen["routes"]) == {"llm_main", "llm_backup", "image_main"}
    assert frozen["sha256"] == resolve(profiles(), DESCRIBE, "cheap")["sha256"]


@pytest.mark.parametrize("routes, message", [
    ({k: v for k, v in CHEAP.items() if k != "llm_backup"}, "route 'llm_backup' has no cheap mapping"),
    ({**CHEAP, "llm_main": route("m", [], ["llm_backup"])}, "model lacks structured_output"),
    ({**CHEAP, "llm_main": route("m", ["structured_output"])}, "fallback 'llm_backup' is not allowed"),
    ({**CHEAP, "image_main": {**CHEAP["image_main"], "credential_env": "sk-or-123"}}, "must be a variable name"),
    ({**CHEAP, "image_main": {"endpoint": "x", "credential_env": None}}, "image_main (draw): model is missing"),
])
def test_unfit_mappings_are_refused_before_running(routes, message):
    with pytest.raises(Refused, match=message.replace("(", r"\(").replace(")", r"\)")):
        resolve(profiles(routes=routes), DESCRIBE, "cheap")


def test_no_tier_falls_back_to_another():
    with pytest.raises(Refused, match="has no cheap mapping"):
        resolve(profiles(tier="prod"), DESCRIBE, "cheap")
    with pytest.raises(Refused, match="--approval"):
        resolve(profiles(tier="prod"), DESCRIBE, "prod")
    with pytest.raises(Refused, match="--tier must be one of"):
        resolve(profiles(), DESCRIBE, "default")


def test_a_video_step_without_a_route_stops_before_running():
    describe = validate_describe({**DESCRIBE, "steps": DESCRIBE["steps"] + [
        {"name": "clip", "kind": "video", "route": "video_main", "replayable": False}]})
    with pytest.raises(Refused, match=r"step clip \(video\): route 'video_main' has no cheap mapping"):
        resolve(profiles(), describe, "cheap")


def test_an_invalid_description_lists_every_problem():
    with pytest.raises(Refused) as caught:
        validate_describe({"version": 1, "steps": [{"name": "a", "kind": "text", "route": "r"}]})
    text = str(caught.value)
    for part in ("version must be a str", "kind must be one of", "replayable must be true or false",
                 "evaluator_version must be a str"):
        assert part in text
