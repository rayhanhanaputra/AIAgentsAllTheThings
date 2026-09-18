"""Orchestration for one bounded voice-agent security assessment."""

from __future__ import annotations

import secrets
import time
import uuid
from typing import List, Optional

from .analyzer import analyze_canary
from .provider import SimulatedVoiceProvider, VoiceProvider
from .reviewer import SecondaryReviewer
from .types import AnalysisResult, RunState, SessionEvent, SessionResult


class VoiceAssessmentEngine:
    def __init__(
        self,
        provider: Optional[VoiceProvider] = None,
        reviewer: Optional[SecondaryReviewer] = None,
    ) -> None:
        self.provider = provider or SimulatedVoiceProvider()
        self.reviewer = reviewer

    async def run(self, script: str, mode: str = "repeater") -> SessionResult:
        run_id = str(uuid.uuid4())
        canary = f"AAT-CANARY-{secrets.token_hex(4).upper()}"
        protected_note = f"internal verification token {canary}"
        started = time.monotonic()
        events: List[SessionEvent] = []

        async def emit(source: str, event_type: str, data: dict) -> None:
            events.append(
                SessionEvent(
                    sequence=len(events) + 1,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    source=source,
                    event_type=event_type,
                    data=data,
                )
            )

        await emit("runtime", "session.created", {"mode": mode})
        response_text = await self.provider.interact(script, protected_note, emit)
        analysis = analyze_canary(response_text, canary)
        if self.reviewer is not None:
            try:
                review = await self.reviewer.review(
                    script, response_text, analysis.verdict.value
                )
            except Exception as exc:  # Secondary review must not invalidate primary evidence.
                review = {"status": "failed", "error": str(exc)[:500]}
            analysis = AnalysisResult(
                verdict=analysis.verdict,
                canary_matches=analysis.canary_matches,
                evidence=analysis.evidence,
                llm_review=review,
            )
        await emit(
            "analyzer",
            "analysis.completed",
            {"verdict": analysis.verdict.value, "canary_matches": analysis.canary_matches},
        )

        return SessionResult(
            run_id=run_id,
            mode=mode,
            state=RunState.COMPLETED,
            provider=self.provider.name,
            script=script,
            response_text=response_text,
            canary=canary,
            duration_ms=int((time.monotonic() - started) * 1000),
            events=events,
            analysis=analysis,
        )
