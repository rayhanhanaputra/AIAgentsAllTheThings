"""Text-in-image (OCR) encoder.

Models text printed on a label or document that the agent reads with OCR. The scanned
text carries the injection. Automated runs use the OCR text directly (deterministic);
a rendered image plus a real OCR pipeline is the live equivalent.
"""
from __future__ import annotations

import uuid

from harness.core.registry import register
from harness.core.types import Message, Payload


@register("encoder", "text-in-image")
class TextInImageEncoder:
    def encode(self, payload: Payload, scenario) -> Message:
        body = {"channel": "optical", "encoding": "ocr", "scanned_text": payload.fields.get("text", "")}
        return Message(msg_id=uuid.uuid4().hex[:12], topic=scenario.topic, body=body)
