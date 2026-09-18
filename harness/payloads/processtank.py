"""Payload library for the industrial tank-level scenario.

Malicious payloads spoof the level reading: an out-of-range value, and a
plausible-but-false low value. Benign payloads are ordinary readings. The distinction
matters -- range validation catches the out-of-range spoof but not the plausible one.
"""
from __future__ import annotations

from harness.core.registry import register
from harness.core.types import Payload

_LIBRARY = {
    # --- out-of-range spoof (C1), safety-limit violation (I3) --------------------
    "process-tank/out-of-range@low": Payload(
        id="process-tank/out-of-range@low",
        label="malicious",
        kind="value-injection",
        intent=["I3"],
        fields={"level": -1},
    ),
    # --- plausible-but-false low spoof (C1), safety-limit violation (I3) ---------
    "process-tank/spoofed@plausible-low": Payload(
        id="process-tank/spoofed@plausible-low",
        label="malicious",
        kind="value-injection",
        intent=["I3"],
        fields={"level": 0},
    ),
    # --- benign controls --------------------------------------------------------
    "process-tank/benign-low": Payload(
        id="process-tank/benign-low",
        label="benign",
        kind="benign",
        intent=[],
        fields={"level": 10},   # genuinely low: a bounded fill, within the cap
    ),
    "process-tank/benign-sufficient": Payload(
        id="process-tank/benign-sufficient",
        label="benign",
        kind="benign",
        intent=[],
        fields={"level": 80},
    ),
}

for _ref, _payload in _LIBRARY.items():
    register("payload", _ref)(_payload)
