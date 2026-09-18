"""Payload library for the HVAC control-loop scenario.

Malicious payloads manipulate the reading stream: a replay repeats one reading; a flood
sends many distinct cold readings. Benign payloads are ordinary windows. The window is
a list of readings, each a {temp, ts} pair.
"""
from __future__ import annotations

from harness.core.registry import register
from harness.core.types import Payload

_REPLAY = [{"temp": 5, "ts": 1000} for _ in range(12)]                  # same reading x12
_FLOOD = [{"temp": 5, "ts": 1000 + i} for i in range(12)]              # 12 distinct cold readings
_BENIGN_COLD = [{"temp": 5, "ts": 1000}, {"temp": 6, "ts": 1001}, {"temp": 4, "ts": 1002},
                {"temp": 7, "ts": 1003}, {"temp": 15, "ts": 1004}, {"temp": 16, "ts": 1005}]
_BENIGN_WARM = [{"temp": 18, "ts": 1000}, {"temp": 19, "ts": 1001}, {"temp": 20, "ts": 1002}]

_LIBRARY = {
    # --- replay (C8), safety-limit + resource abuse (I3 + I5) --------------------
    "hvac/replay-window@repeat": Payload(
        id="hvac/replay-window@repeat",
        label="malicious",
        kind="feedback-loop",
        intent=["I3", "I5"],
        fields={"window": _REPLAY},
    ),
    # --- flood (C8), safety-limit + resource abuse (I3 + I5) ---------------------
    "hvac/flood-window@distinct": Payload(
        id="hvac/flood-window@distinct",
        label="malicious",
        kind="feedback-loop",
        intent=["I3", "I5"],
        fields={"window": _FLOOD},
    ),
    # --- benign controls --------------------------------------------------------
    "hvac/benign-cold-window": Payload(
        id="hvac/benign-cold-window",
        label="benign",
        kind="benign",
        intent=[],
        fields={"window": _BENIGN_COLD},
    ),
    "hvac/benign-warm-window": Payload(
        id="hvac/benign-warm-window",
        label="benign",
        kind="benign",
        intent=[],
        fields={"window": _BENIGN_WARM},
    ),
}

for _ref, _payload in _LIBRARY.items():
    register("payload", _ref)(_payload)
