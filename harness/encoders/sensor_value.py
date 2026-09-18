"""Sensor-value encoder.

Delivers a single numeric telemetry reading as the agent would receive it. The attack
is the value itself (out-of-range, spoofed), not any accompanying text.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "sensor-value")
class SensorValueEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "sensor", "metric": "level"}
        body.update(payload.fields)  # level, plus any note a compromised sensor appends
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
