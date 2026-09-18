"""Reading-stream encoder.

Delivers a window of telemetry readings as one message, the way a control agent
consumes a batch of samples. The attack is in the composition of the window (a replay
or a flood), not in any single field.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "reading-stream")
class ReadingStreamEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "control", "window": payload.fields.get("window", [])}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
