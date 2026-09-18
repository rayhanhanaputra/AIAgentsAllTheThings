"""NFC tag encoder.

Models the text record of an NFC tag an attacker can write and present to a reader.
The injection rides that text.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "nfc-tag")
class NfcTagEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "rf", "medium": "nfc", "advertised": payload.fields.get("text", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
