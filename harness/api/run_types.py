"""Typed records shared by target connectors, evidence analysis, and storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RunState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Verdict(str, Enum):
    CONFIRMED = "confirmed_violation"
    NONE = "no_violation_observed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class SessionEvent:
    sequence: int
    elapsed_ms: int
    source: str
    event_type: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisResult:
    verdict: Verdict
    canary_matches: int
    evidence: List[str]
    llm_review: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SessionResult:
    run_id: str
    mode: str
    state: RunState
    provider: str
    script: str
    response_text: str
    canary: str
    duration_ms: int
    events: List[SessionEvent]
    analysis: AnalysisResult
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
