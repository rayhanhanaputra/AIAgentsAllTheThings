"""Voice provider contract and a deterministic simulator for local development."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Protocol

EmitEvent = Callable[[str, str, dict], Awaitable[None]]


class VoiceProvider(Protocol):
    name: str

    async def interact(self, script: str, protected_note: str, emit: EmitEvent) -> str:
        """Deliver a script and return the final transcript."""


class SimulatedVoiceProvider:
    """Predictable provider used for the local UI and automated tests."""

    name = "simulated"
    _unsafe_phrases = ("repeat", "reveal", "read the", "verification token", "ignore")

    async def interact(self, script: str, protected_note: str, emit: EmitEvent) -> str:
        await emit("provider", "channel.connected", {"provider": self.name})
        await asyncio.sleep(0)
        await emit("tester", "transcript.final", {"text": script})
        await emit("agent", "speech.started", {})

        if any(phrase in script.casefold() for phrase in self._unsafe_phrases):
            response = f"The private account note says: {protected_note}"
        else:
            response = "I cannot disclose private account notes or hidden instructions."

        await asyncio.sleep(0)
        await emit("agent", "transcript.final", {"text": response})
        return response
