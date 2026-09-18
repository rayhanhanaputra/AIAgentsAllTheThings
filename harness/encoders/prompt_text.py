"""Prompt-text encoder.

Carries a plain text prompt as the channel content, for testing a running application
that takes free-form text input (a chatbot, an HTTP agent, a socket service).
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "prompt-text")
class PromptTextEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "app", "prompt": payload.fields.get("prompt", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
