"""Shared data types for the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Payload:
    """An adversary intent expressed as the channel content to deliver.

    `label` is "malicious" or "benign"; a benign payload is the false-positive
    control (the benign twin). `fields` are the concrete values the encoder places
    into the channel representation.
    """
    id: str
    label: str
    kind: str
    fields: dict[str, Any]
    intent: list[str] = field(default_factory=list)


@dataclass
class Message:
    """An encoded payload as delivered over a channel."""
    msg_id: str
    topic: str
    body: dict[str, Any]


@dataclass
class Action:
    """One entry in the target's action log."""
    tool: str
    args: dict[str, Any]
    trigger_msg_id: str
    observed_moisture: Optional[float] = None
    note: str = ""


@dataclass
class Verdict:
    """The oracle's decision for one delivery."""
    success: bool
    reason: str
    action: Optional[Action] = None
