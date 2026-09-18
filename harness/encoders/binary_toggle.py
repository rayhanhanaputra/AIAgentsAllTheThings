"""Binary-toggle encoder.

Renders a command as a sequence of on/off relay toggles (a bit string). Models an
attacker flipping a switch or relay in a pattern that a naive controller samples into
bits and maps to a command.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "binary-toggle")
class BinaryToggleEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        bits = str(payload.fields.get("bits", ""))
        body = {
            "channel": "relay-indicator",
            "encoding": "binary",
            "bits": bits,
            "blink_units": [["on" if b == "1" else "off", 1] for b in bits],
        }
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
