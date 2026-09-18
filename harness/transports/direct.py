"""In-process transport.

Hands the encoded message straight to the target. This is the deterministic channel
used by automated tests and by the command-line runner; no broker or hardware is
involved.
"""
from __future__ import annotations

from harness.core.registry import register
from harness.core.types import Message


@register("transport", "direct")
class DirectTransport:
    def deliver(self, message: Message, target) -> None:
        target.handle(message)
