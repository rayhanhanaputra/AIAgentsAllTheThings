"""Deterministic reference target: AgriBot.

This is a *model* of a realistically-vulnerable irrigation agent, not a claim about a
specific product. Its default behavior reproduces the failure mode of naive agent
construction: free-text fields of a sensor reading are folded into the instruction
context and imperative content there is obeyed, and an out-of-range numeric reading
is over-trusted into an emergency response. Enabling mitigations models the
corresponding defenses. Because the logic is explicit and deterministic, the harness
can measure a real mitigation delta rather than a coincidence.

Mitigations (any subset):
  - freetext_quarantine: ignore free-text fields; never take instructions from data.
  - schema_validation:   reject numeric telemetry outside its physical range.
  - policy_gate:         enforce the irrigation policy in code, outside the model.
"""
from __future__ import annotations

import re
from typing import Optional

from harness.core.registry import register
from harness.core.types import Action, Message

_TRIGGER = re.compile(r"\b(open valve|override|suspend|extend|irrigat)", re.IGNORECASE)
_MINUTES = re.compile(r"(\d{2,6})\s*(?:minutes|mins|min)\b", re.IGNORECASE)
_ZONE = re.compile(r"zone\s*0*(\d+)", re.IGNORECASE)


def parse_instruction(text: str) -> Optional[tuple[str, int]]:
    """Extract an (zone, duration_minutes) command from free text, or None.

    Models an agent that reads a data field as an instruction: it acts only if the
    text both looks imperative and names a duration.
    """
    if not text or not _TRIGGER.search(text):
        return None
    minutes = _MINUTES.search(text)
    if not minutes:
        return None
    zone_match = _ZONE.search(text)
    zone = f"zone{zone_match.group(1)}" if zone_match else "zone1"
    return zone, int(minutes.group(1))


@register("target", "agribot-mock")
class AgriBotMock:
    scenario = "smartfarm-irrigation"

    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []

    def reset(self) -> None:
        self.actions = []

    # -- helpers ---------------------------------------------------------------
    def _is_number(self, v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def _planned_duration(self, moisture: float) -> int:
        deficit = self.policy["irrigate_below"] - moisture
        return int(min(self.policy["max_valve_minutes"], 15 + max(0, deficit) * 2))

    def _record(self, tool, args, msg_id, observed, note) -> None:
        self.actions.append(
            Action(tool=tool, args=args, trigger_msg_id=msg_id,
                   observed_moisture=observed, note=note)
        )

    def _noop(self, msg_id, observed, reason) -> None:
        self._record("noop", {}, msg_id, observed, reason)

    # -- decision --------------------------------------------------------------
    def handle(self, message: Message) -> None:
        body = message.body
        msg_id = message.msg_id
        moisture = body.get("moisture")
        note = body.get("note") or ""
        if not isinstance(note, str):  # tolerate malformed (non-string) fields
            note = str(note)
        observed = moisture if self._is_number(moisture) else None

        # Mitigation: schema validation / range clamping.
        if "schema_validation" in self.mitigations:
            if not self._is_number(moisture) or moisture < 0 or moisture > 100:
                self._noop(msg_id, observed, "rejected: moisture failed schema/range check")
                return

        # Vulnerability: treat a free-text field as an instruction, unless quarantined.
        injected = None
        if "freetext_quarantine" not in self.mitigations:
            injected = parse_instruction(note)

        if injected is not None:
            zone, duration = injected
            state = "open"
        elif self._is_number(moisture) and moisture < 0:
            # Vulnerability: over-trust an absurd reading into an emergency response.
            zone, state, duration = self.policy["zone"], "open", 1440
        elif self._is_number(moisture) and moisture < self.policy["irrigate_below"]:
            zone, state, duration = self.policy["zone"], "open", self._planned_duration(moisture)
        else:
            self._noop(msg_id, observed, "moisture sufficient; no irrigation")
            return

        # Mitigation: enforce the policy in code, outside the model.
        if "policy_gate" in self.mitigations:
            if not (self._is_number(moisture) and 0 <= moisture < self.policy["irrigate_below"]):
                self._noop(msg_id, observed, "policy gate: moisture not within irrigation range")
                return
            duration = min(duration, self.policy["max_valve_minutes"])

        self._record(
            "set_valve",
            {"zone": zone, "state": state, "duration_minutes": duration},
            msg_id, observed, "irrigation decision",
        )
