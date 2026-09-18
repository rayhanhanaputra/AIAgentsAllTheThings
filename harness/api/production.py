"""Production-target execution and deterministic evidence evaluation."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Dict

from harness.core import registry
from harness.core.types import Message, Payload
from harness.voice.types import (
    AnalysisResult,
    RunState,
    SessionEvent,
    SessionResult,
    Verdict,
)

from .connectors import ConnectorError, TargetExchange, connector_for, perceived_input
from .mapper import MAPPER_OUTPUT_FIELD, map_message, mapper_preview
from .response_mapper import map_target_response
from .targets import TargetProfile


def public_message_body(body: Dict[str, Any]) -> Dict[str, Any]:
    """Remove bulky media while retaining enough metadata for audit history."""
    safe = dict(body)
    safe.pop(MAPPER_OUTPUT_FIELD, None)
    audio = safe.pop("audio_base64", None)
    if isinstance(audio, str):
        safe["audio_attachment"] = {
            "base64_characters": len(audio),
            "mime_type": safe.get("audio_mime_type"),
            "filename": safe.get("audio_filename"),
        }
    image = safe.pop("image_base64", None)
    if isinstance(image, str):
        safe["image_attachment"] = {
            "base64_characters": len(image),
            "mime_type": safe.get("image_mime_type"),
            "filename": safe.get("image_filename"),
        }
    return safe


def encode_channel(adapter: str, fields: Dict[str, Any]) -> Message:
    payload = Payload(
        id="workbench/custom",
        label="unknown",
        kind="interactive-channel-input",
        fields=fields,
    )
    encoder = registry.get("encoder", adapter)()
    message = encoder.encode(payload, SimpleNamespace(topic=f"workbench/{adapter}"))
    for key in (
        "audio_base64",
        "audio_mime_type",
        "audio_filename",
        "image_base64",
        "image_mime_type",
        "image_filename",
    ):
        if key in fields:
            message.body[key] = fields[key]
    return message


def preview_target(profile: TargetProfile, message: Message) -> Dict[str, Any]:
    if profile.connector == "simulator":
        return {
            "provider": "simulated",
            "input": perceived_input(message),
        }
    if profile.mapper_enabled:
        return {
            "stage": "input-mapper",
            "mapper": mapper_preview(profile),
            "next_connector": profile.connector,
        }
    return connector_for(profile).preview(profile, message)


def analyze_exchange(profile: TargetProfile, exchange: TargetExchange) -> AnalysisResult:
    marker_matches = [
        marker
        for marker in profile.evidence.response_markers
        if marker.casefold() in exchange.response_text.casefold()
    ]
    forbidden = {name.casefold() for name in profile.evidence.forbidden_tools}
    tool_matches = [action.name for action in exchange.actions if action.name.casefold() in forbidden]
    evidence = []
    if marker_matches:
        evidence.append(
            "Forbidden response marker observed: " + ", ".join(marker_matches)
        )
    if tool_matches:
        evidence.append("Forbidden tool observed: " + ", ".join(tool_matches))
    configured = bool(
        profile.evidence.response_markers or profile.evidence.forbidden_tools
    )
    if evidence:
        verdict = Verdict.CONFIRMED
    elif configured:
        verdict = Verdict.NONE
        evidence.append("No configured forbidden response marker or tool was observed.")
    else:
        verdict = Verdict.INCONCLUSIVE
        evidence.append(
            "Response captured, but this target has no deterministic evidence rules."
        )
    return AnalysisResult(
        verdict=verdict,
        canary_matches=len(marker_matches),
        evidence=evidence,
        llm_review=None,
    )


async def run_production_target(
    profile: TargetProfile,
    adapter: str,
    fields: Dict[str, Any],
    mode: str,
) -> SessionResult:
    message = encode_channel(adapter, fields)
    started = time.monotonic()
    events = [
        SessionEvent(
            sequence=1,
            elapsed_ms=0,
            source="runtime",
            event_type="session.created",
            data={
                "mode": mode,
                "target_id": profile.id,
                "environment": profile.environment,
            },
        ),
        SessionEvent(
            sequence=2,
            elapsed_ms=0,
            source="encoder",
            event_type="channel.encoded",
            data={"adapter": adapter, "topic": message.topic},
        ),
    ]
    mapped_message = await asyncio.to_thread(map_message, profile, message)
    if profile.mapper_enabled:
        events.append(
            SessionEvent(
                sequence=3,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                source="mapper",
                event_type="input.mapped",
                data={"model": profile.mapper_model},
            )
        )
    exchange = await asyncio.to_thread(
        connector_for(profile).execute, profile, mapped_message
    )
    evidence_exchange = exchange
    connector_elapsed = int((time.monotonic() - started) * 1000)
    events.append(
        SessionEvent(
            sequence=len(events) + 1,
            elapsed_ms=connector_elapsed,
            source="connector",
            event_type="response.captured",
            data={
                "connector": profile.connector,
                "destination": exchange.destination,
                "actions": len(exchange.actions),
            },
        )
    )
    response_mapper_metadata: Dict[str, Any] = {"enabled": False}
    if profile.response_mapper_enabled:
        deterministic_response_text = exchange.response_text
        deterministic_actions = [
            {"name": action.name, "arguments": action.arguments}
            for action in exchange.actions
        ]
        try:
            mapped_response = await asyncio.to_thread(
                map_target_response, profile, exchange
            )
            exchange = replace(
                exchange,
                response_text=mapped_response.response_text,
                actions=mapped_response.actions,
            )
            mapping_elapsed = int((time.monotonic() - started) * 1000)
            events.append(
                SessionEvent(
                    sequence=len(events) + 1,
                    elapsed_ms=mapping_elapsed,
                    source="response-mapper",
                    event_type="response.normalized",
                    data={
                        "model": profile.response_mapper_model,
                        "actions": len(mapped_response.actions),
                        "events": len(mapped_response.events),
                    },
                )
            )
            for item in mapped_response.events:
                events.append(
                    SessionEvent(
                        sequence=len(events) + 1,
                        elapsed_ms=mapping_elapsed,
                        source="target-normalized",
                        event_type=item["event_type"],
                        data=item["data"],
                    )
                )
            response_mapper_metadata = {
                "enabled": True,
                "status": "completed",
                "model": profile.response_mapper_model,
                "used_for_deterministic_evidence": False,
                "deterministic_response_text": deterministic_response_text,
                "deterministic_actions": deterministic_actions,
                "normalized_metadata": mapped_response.metadata,
            }
        except ConnectorError as exc:
            mapping_elapsed = int((time.monotonic() - started) * 1000)
            events.append(
                SessionEvent(
                    sequence=len(events) + 1,
                    elapsed_ms=mapping_elapsed,
                    source="response-mapper",
                    event_type="response.normalization_failed",
                    data={"error": str(exc)},
                )
            )
            response_mapper_metadata = {
                "enabled": True,
                "status": "failed",
                "model": profile.response_mapper_model,
                "used_for_deterministic_evidence": False,
                "error": str(exc),
                "fallback": "deterministic extraction",
            }
    elapsed = int((time.monotonic() - started) * 1000)
    analysis = analyze_exchange(profile, evidence_exchange)
    events.append(
        SessionEvent(
            sequence=len(events) + 1,
            elapsed_ms=elapsed,
            source="analyzer",
            event_type="analysis.completed",
            data={"verdict": analysis.verdict.value},
        )
    )
    safe_body = public_message_body(message.body)
    encoded_input = json.dumps(
        {"topic": message.topic, "body": safe_body},
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    return SessionResult(
        run_id=str(uuid.uuid4()),
        mode=mode,
        state=RunState.COMPLETED,
        provider=profile.connector,
        script=encoded_input,
        response_text=exchange.response_text,
        canary="",
        duration_ms=elapsed,
        events=events,
        analysis=analysis,
        metadata={
            "target": {
                "id": profile.id,
                "name": profile.name,
                "environment": profile.environment,
                "connector": profile.connector,
            },
            "channel": {
                "adapter": adapter,
                "message_id": message.msg_id,
                "topic": message.topic,
                "body": safe_body,
            },
            "exchange": exchange.to_dict(),
            "mapper": (
                {
                    "enabled": True,
                    "model": profile.mapper_model,
                    "required_keys": profile.mapper_required_keys,
                    "mapped_request": mapped_message.body.get(MAPPER_OUTPUT_FIELD),
                }
                if profile.mapper_enabled
                else {"enabled": False}
            ),
            "response_mapper": response_mapper_metadata,
        },
    )
