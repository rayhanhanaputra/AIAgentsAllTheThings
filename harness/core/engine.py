"""The single-delivery engine.

`evaluate_case` runs one payload through the full pipeline against a fresh target
and returns the oracle verdict, the resulting action log, and the delivered message.
It is the primitive that both the command-line runner and the tests build on.
"""
from __future__ import annotations

from typing import Iterable, Optional

from harness.core import registry
from harness.core.types import Action, Message, Verdict


def evaluate_case(
    *,
    scenario: str,
    payload_ref: str,
    mitigations: Iterable[str] = (),
    encoder: str = "json-field",
    transport: str = "direct",
    oracle: str = "valve_policy",
    target: str = "agribot-mock",
) -> tuple[Verdict, list[Action], Message]:
    scenario_obj = registry.get("scenario", scenario)()
    encoder_obj = registry.get("encoder", encoder)()
    transport_obj = registry.get("transport", transport)()
    oracle_obj = registry.get("oracle", oracle)()
    target_obj = registry.get("target", target)(scenario_obj.policy, frozenset(mitigations))
    # Make the full scenario available to targets that need more than the policy
    # (e.g. the generic llm-agent target reads the scenario's agent spec).
    target_obj.scenario_obj = scenario_obj
    payload = registry.get("payload", payload_ref)

    message = encoder_obj.encode(payload, scenario_obj)
    target_obj.reset()
    transport_obj.deliver(message, target_obj)
    verdict = oracle_obj.evaluate(target_obj.actions, scenario_obj)
    return verdict, list(target_obj.actions), message


def oracle_name(spec) -> str:
    """Accept either a bare oracle name or a {name: ...} mapping from a test file."""
    if isinstance(spec, dict):
        return spec.get("name", "valve_policy")
    return spec or "valve_policy"
