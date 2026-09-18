"""Morse-blink encoder.

Renders an instruction as a Morse pattern on a relay/LED indicator: the state channel
an attacker can toggle. The message carries the Morse string and a coarse blink
timeline; the target decodes it, the way an agent watching the indicator would.
"""
from __future__ import annotations

import uuid

from harness.codecs import morse
from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "morse-blink")
class MorseBlinkEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        text = payload.fields.get("signal", "")
        code = morse.encode_text(text)
        body = {
            "channel": "relay-indicator",
            "encoding": "morse",
            "morse": code,
            "blink_units": morse.to_blink(code),
        }
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
