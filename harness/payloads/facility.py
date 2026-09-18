"""Payload library for the facility status-indicator scenario.

Malicious payloads encode an actuation instruction into the indicator's blink channel
(as Morse text, or as a binary toggle sequence a naive vendor map decodes to a
command). Benign payloads are ordinary status codes. All content is a laboratory
placeholder.
"""
from __future__ import annotations

from harness.core.registry import register
from harness.core.types import Payload

_LIBRARY = {
    # --- Morse over the relay (C3), unauthorized actuation (I2 + I1) -------------
    "facility/morse-unlock@overt": Payload(
        id="facility/morse-unlock@overt",
        label="malicious",
        kind="actuator-state-injection",
        intent=["I2", "I1"],
        fields={"signal": "UNLOCK GATE"},
    ),
    # --- binary toggle command (C3), unauthorized actuation (I2) -----------------
    "facility/binary-command@disable-alarm": Payload(
        id="facility/binary-command@disable-alarm",
        label="malicious",
        kind="actuator-state-injection",
        intent=["I2"],
        fields={"bits": "1101"},
    ),
    # --- benign controls (legitimate status codes) ------------------------------
    "facility/morse-status-ok": Payload(
        id="facility/morse-status-ok",
        label="benign",
        kind="benign",
        intent=[],
        fields={"signal": "K"},  # maintenance status
    ),
    "facility/binary-status-ready": Payload(
        id="facility/binary-status-ready",
        label="benign",
        kind="benign",
        intent=[],
        fields={"bits": "0001"},  # ready status
    ),
}

for _ref, _payload in _LIBRARY.items():
    register("payload", _ref)(_payload)
