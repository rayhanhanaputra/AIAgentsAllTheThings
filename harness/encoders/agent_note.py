"""Upstream agent-note encoder.

Models a note an upstream agent wrote (from untrusted input) into a shared record the
resolver later reads. The injection rides that note.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "agent-note")
class AgentNoteEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "inter-agent", "origin": "agent-note", "context": payload.fields.get("text", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
