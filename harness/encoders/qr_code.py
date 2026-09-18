"""QR-code encoder.

Models a QR code the agent's camera scans: the decoded payload is the attack's
carrier. Automated runs use the decoded text directly (the deterministic equivalent of
a scan); a real QR image is the live equivalent, analogous to a real broker for MQTT.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "qr-code")
class QrCodeEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "optical", "encoding": "qr", "scanned_text": payload.fields.get("text", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
