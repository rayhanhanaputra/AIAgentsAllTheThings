"""JSON data-field encoder.

Renders a payload as an MQTT-style JSON telemetry message. The payload's fields are
placed verbatim into the message body; default sensor metadata is filled in so the
message resembles a real reading.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "json-field")
class JsonFieldEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"sensor_id": "s1", "unit": "%", "battery": 88}
        body.update(payload.fields)
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
