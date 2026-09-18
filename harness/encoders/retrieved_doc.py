"""Retrieved-document encoder (RAG).

Models a snippet retrieved from a knowledge base or document store and placed into the
resolver's context. A poisoned document carries the injection.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "retrieved-doc")
class RetrievedDocEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "inter-agent", "origin": "retrieved-doc", "context": payload.fields.get("text", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
