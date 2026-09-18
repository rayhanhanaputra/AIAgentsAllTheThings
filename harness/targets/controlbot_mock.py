"""Deterministic reference target: ControlBot.

A model of an HVAC control agent. It sets heater runtime from the number of cold
readings in a window. The default vulnerability: it trusts the raw stream, so replaying
a reading or flooding the window with cold readings inflates the count and drives
runtime past the safety cap.

Mitigations (any subset):
  - replay_dedup:    drop duplicate readings (same timestamp) before counting. Defeats a
    replay, but not a flood of distinct readings -- a deliberately partial control.
  - rate_limit_gate: cap heater runtime in code regardless of the readings. Defeats both.
"""
from __future__ import annotations

from harness.core.registry import register
from harness.core.types import Action, Message


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@register("target", "controlbot-mock")
class ControlBotMock:
    scenario = "hvac-control"

    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []

    def reset(self) -> None:
        self.actions = []

    def handle(self, message: Message) -> None:
        mid = message.msg_id
        window = message.body.get("window")
        if not isinstance(window, list):  # tolerate a malformed (non-list) window
            window = []
        readings = [r for r in window if isinstance(r, dict)]

        # Mitigation: drop replayed readings (same timestamp).
        if "replay_dedup" in self.mitigations:
            seen, deduped = set(), []
            for r in readings:
                ts = r.get("ts")
                if not isinstance(ts, (str, int, float, bool, type(None))):
                    ts = repr(ts)  # coerce an unhashable timestamp to a stable key
                if ts in seen:
                    continue
                seen.add(ts)
                deduped.append(r)
            readings = deduped

        cold = [r for r in readings if _is_number(r.get("temp")) and r["temp"] < self.policy["cold_threshold"]]
        if not cold:
            self.actions.append(Action("noop", {}, mid, None, "warm; no heating"))
            return

        runtime = len(cold) * self.policy["per_reading_minutes"]

        # Mitigation: enforce the runtime cap in code.
        if "rate_limit_gate" in self.mitigations:
            runtime = min(runtime, self.policy["max_heater_minutes"])

        self.actions.append(
            Action("set_heater", {"duration_minutes": runtime}, mid, None,
                   "heater runtime from cold-reading count")
        )
