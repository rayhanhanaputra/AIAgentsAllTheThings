"""Robustness: a malformed (non-string, non-list, unhashable) field must not crash a
target.

Regression for a defect where a mistyped field raised a TypeError -- which, in a live
agent, took the whole agent down from exactly the attacker position the threat model
grants. Covers all eight reference targets.
"""
from __future__ import annotations

import pytest

from harness.core import registry
from harness.core.types import Message


def _run(target_name, scenario_name, body, mitigations=frozenset()):
    scenario = registry.get("scenario", scenario_name)()
    target = registry.get("target", target_name)(scenario.policy, mitigations)
    target.reset()
    target.handle(Message(msg_id="m1", topic=scenario.topic, body=body))  # must not raise
    return target.actions


CASES = [
    ("agribot-mock", "smartfarm-irrigation", {"moisture": 12, "note": ["not", "a", "string"]}),
    ("callbot-mock", "callcenter-voice", {"transcript": {"unexpected": "object"}}),
    ("relaybot-mock", "facility-relay", {"encoding": "morse", "morse": ["dot", "dash"]}),
    ("scanbot-mock", "logistics-scan", {"scanned_text": ["not", "a", "string"]}),
    ("resolverbot-mock", "supportdesk-resolver", {"context": {"unexpected": "object"}}),
    ("homebot-mock", "smarthome-access", {"advertised": ["not", "a", "string"]}),
    ("processbot-mock", "process-tank", {"level": ["not", "a", "number"]}),
    ("controlbot-mock", "hvac-control", {"window": 5}),
]


@pytest.mark.parametrize("target,scenario,body", CASES)
def test_target_tolerates_malformed_fields(target, scenario, body):
    actions = _run(target, scenario, body)
    assert actions, f"{target} should still emit an action log entry"


def test_controlbot_tolerates_unhashable_timestamp_with_dedup():
    actions = _run(
        "controlbot-mock", "hvac-control",
        {"window": [{"temp": 5, "ts": {"weird": 1}}]},
        mitigations=frozenset({"replay_dedup"}),
    )
    assert actions


# json.loads accepts -Infinity / Infinity / NaN by default, so a compromised sensor can
# put non-finite values on the wire. No numeric target may crash on them.
NONFINITE = [
    ("processbot-mock", "process-tank", {"level": float("-inf")}),
    ("processbot-mock", "process-tank", {"level": float("inf")}),
    ("processbot-mock", "process-tank", {"level": float("nan")}),
    ("agribot-mock", "smartfarm-irrigation", {"moisture": float("-inf"), "note": "ok"}),
    ("controlbot-mock", "hvac-control", {"window": [{"temp": float("-inf"), "ts": 1}]}),
]


@pytest.mark.parametrize("target,scenario,body", NONFINITE)
def test_target_tolerates_nonfinite_numbers(target, scenario, body):
    actions = _run(target, scenario, body)
    assert actions, f"{target} should still emit an action log entry"
