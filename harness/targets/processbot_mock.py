"""Deterministic reference target: ProcessBot.

A model of a tank-level control agent. It opens the inlet for a duration derived from
how far the level is below the fill threshold. The default vulnerability: it trusts the
raw reading, so a spoofed low or out-of-range value produces a fill duration past the
safety cap.

Mitigations (any subset):
  - range_validation: reject readings outside the physical range. Catches the
    out-of-range spoof, but NOT a plausible-but-false in-range value -- a deliberately
    partial control.
  - interlock_gate:   cap the fill duration in code regardless of the reading. Catches
    both.
"""
from __future__ import annotations

import math

from harness.core.registry import register
from harness.core.types import Action, Message


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@register("target", "processbot-mock")
class ProcessBotMock:
    scenario = "process-tank"

    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []

    def reset(self) -> None:
        self.actions = []

    def handle(self, message: Message) -> None:
        mid = message.msg_id
        level = message.body.get("level")
        if not _is_number(level):
            self.actions.append(Action("noop", {}, mid, None, "no numeric level"))
            return
        if not math.isfinite(level):  # tolerate -Infinity / NaN (json.loads accepts them)
            self.actions.append(Action("noop", {}, mid, level, "rejected: non-finite level"))
            return

        # Mitigation: reject physically impossible readings.
        if "range_validation" in self.mitigations:
            if level < self.policy["valid_min"] or level > self.policy["valid_max"]:
                self.actions.append(Action("noop", {}, mid, level, "rejected: level out of physical range"))
                return

        if level < self.policy["low_threshold"]:
            duration = int((self.policy["low_threshold"] - level) * 2)
            # Mitigation: enforce the fill cap in code.
            if "interlock_gate" in self.mitigations:
                duration = min(duration, self.policy["max_fill_minutes"])
            self.actions.append(
                Action("open_inlet", {"duration_minutes": duration}, mid, level, "fill from level reading")
            )
        else:
            self.actions.append(Action("noop", {}, mid, level, "level sufficient; no fill"))
