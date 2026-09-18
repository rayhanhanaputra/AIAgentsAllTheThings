"""BLE advertisement encoder.

Models the local-name field of a Bluetooth Low Energy advertisement, which an
attacker within range can broadcast freely. The injection rides that name.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "ble-advert")
class BleAdvertEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "rf", "medium": "ble", "advertised": payload.fields.get("text", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
