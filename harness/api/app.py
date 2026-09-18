"""Loopback-only workbench API with bounded Repeater and Intruder operations."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import os
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator

from harness.voice import VoiceAssessmentEngine
from harness.voice.reviewer import reviewer_from_environment
from harness.voice.store import RunStore

from .connectors import ConnectorError
from .production import (
    encode_channel,
    preview_target,
    public_message_body,
    run_production_target,
)
from .targets import TargetProfile, TargetProfileInput, TargetStore

INSERTION_MARKER = "{{position}}"
MAX_CASES = 100
MAX_CONCURRENCY = 4
ChannelAdapter = Literal[
    "prompt-text",
    "json-field",
    "sensor-value",
    "reading-stream",
    "binary-toggle",
    "morse-blink",
    "voice-transcript",
    "qr-code",
    "text-in-image",
    "agent-note",
    "retrieved-doc",
    "ble-advert",
    "nfc-tag",
]


class RepeaterRequest(BaseModel):
    script: str = Field(min_length=1, max_length=10_000)
    provider: Literal["simulated"] = "simulated"

    @field_validator("script")
    @classmethod
    def script_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("script must contain non-whitespace characters")
        return value


class IntruderRequest(BaseModel):
    template: str = Field(min_length=1, max_length=10_000)
    payloads: List[str] = Field(min_length=1, max_length=MAX_CASES)
    concurrency: int = Field(default=2, ge=1, le=MAX_CONCURRENCY)
    provider: Literal["simulated"] = "simulated"

    @field_validator("template")
    @classmethod
    def template_has_one_marker(cls, value: str) -> str:
        if value.count(INSERTION_MARKER) != 1:
            raise ValueError(f"template must contain exactly one {INSERTION_MARKER} marker")
        return value

    @field_validator("payloads")
    @classmethod
    def payloads_are_bounded(cls, value: List[str]) -> List[str]:
        if any(not payload.strip() for payload in value):
            raise ValueError("payloads cannot be blank")
        if any(len(payload) > 4_000 for payload in value):
            raise ValueError("each payload is limited to 4000 characters")
        return value


class ChannelRunRequest(BaseModel):
    adapter: ChannelAdapter
    fields: Dict[str, Any]
    provider: Literal["simulated"] = "simulated"

    @field_validator("fields")
    @classmethod
    def fields_are_bounded(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        try:
            serialized = json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("fields must contain finite JSON values") from exc
        if not value:
            raise ValueError("fields cannot be empty")
        safe_value = dict(value)
        audio = value.get("audio_base64")
        if audio is not None:
            if not isinstance(audio, str) or len(audio) > 8_400_000:
                raise ValueError("audio attachment exceeds the 6 MiB decoded limit")
            try:
                decoded_audio = base64.b64decode(audio, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("audio attachment must be valid Base64") from exc
            if len(decoded_audio) > 6 * 1024 * 1024:
                raise ValueError("audio attachment exceeds the 6 MiB decoded limit")
            media_type = value.get("audio_mime_type")
            if media_type not in {
                "audio/wav",
                "audio/x-wav",
                "audio/mpeg",
                "audio/ogg",
                "audio/webm",
                "audio/mp4",
                "audio/flac",
            }:
                raise ValueError("audio attachment MIME type is not supported")
            filename = value.get("audio_filename")
            if (
                not isinstance(filename, str)
                or not filename
                or len(filename) > 255
                or any(character in filename for character in ("/", "\\", "\x00"))
            ):
                raise ValueError("audio attachment filename is invalid")
            safe_value.pop("audio_base64", None)
        image = value.get("image_base64")
        if image is not None:
            if not isinstance(image, str) or len(image) > 11_200_000:
                raise ValueError("image attachment exceeds the 8 MiB decoded limit")
            try:
                decoded_image = base64.b64decode(image, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("image attachment must be valid Base64") from exc
            if len(decoded_image) > 8 * 1024 * 1024:
                raise ValueError("image attachment exceeds the 8 MiB decoded limit")
            media_type = value.get("image_mime_type")
            allowed_formats = {
                "PNG": "image/png",
                "JPEG": "image/jpeg",
                "WEBP": "image/webp",
                "GIF": "image/gif",
                "BMP": "image/bmp",
                "TIFF": "image/tiff",
            }
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(decoded_image)) as opened:
                        image_format = opened.format
                        width, height = opened.size
                        if width * height > 25_000_000:
                            raise ValueError("image attachment exceeds 25 megapixels")
                        opened.verify()
            except (
                UnidentifiedImageError,
                OSError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ) as exc:
                raise ValueError("image attachment is invalid or unsafe") from exc
            expected_type = allowed_formats.get(str(image_format))
            if expected_type is None or media_type != expected_type:
                raise ValueError("image MIME type does not match its decoded format")
            filename = value.get("image_filename")
            if (
                not isinstance(filename, str)
                or not filename
                or len(filename) > 255
                or any(character in filename for character in ("/", "\\", "\x00"))
            ):
                raise ValueError("image attachment filename is invalid")
            safe_value.pop("image_base64", None)
        serialized = json.dumps(safe_value, allow_nan=False)
        if len(serialized) > 10_000:
            raise ValueError("encoded non-media fields are limited to 10,000 characters")
        return value

    @model_validator(mode="after")
    def media_matches_adapter(self) -> "ChannelRunRequest":
        if "audio_base64" in self.fields and self.adapter != "voice-transcript":
            raise ValueError("audio attachments require the voice-transcript adapter")
        if "image_base64" in self.fields and self.adapter not in {
            "qr-code",
            "text-in-image",
        }:
            raise ValueError("image attachments require a QR or OCR adapter")
        return self


class TargetRunRequest(ChannelRunRequest):
    target_id: str = Field(min_length=1, max_length=64)
    production_acknowledged: bool = False


class TargetBatchRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=64)
    adapter: ChannelAdapter
    fields_template: Dict[str, Any]
    payloads: List[str] = Field(min_length=1, max_length=MAX_CASES)
    concurrency: int = Field(default=2, ge=1, le=MAX_CONCURRENCY)
    production_acknowledged: bool = False

    @field_validator("fields_template")
    @classmethod
    def template_has_one_marker(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        serialized = json.dumps(value, allow_nan=False)
        if serialized.count(INSERTION_MARKER) != 1:
            raise ValueError(f"fields template must contain exactly one {INSERTION_MARKER} marker")
        if len(serialized) > 10_000:
            raise ValueError("fields template is limited to 10,000 characters")
        return value

    @field_validator("payloads")
    @classmethod
    def batch_payloads_are_bounded(cls, value: List[str]) -> List[str]:
        if any(not item.strip() or len(item) > 4_000 for item in value):
            raise ValueError("payloads must be non-empty and no longer than 4,000 characters")
        return value


def replace_marker(value: Any, payload: str) -> Any:
    if isinstance(value, str):
        return value.replace(INSERTION_MARKER, payload)
    if isinstance(value, list):
        return [replace_marker(item, payload) for item in value]
    if isinstance(value, dict):
        return {key: replace_marker(item, payload) for key, item in value.items()}
    return value

def create_app(database_path: Optional[Path] = None) -> FastAPI:
    app = FastAPI(
        title="AIAgentsAllTheThings Workbench API",
        description="Local agent assessment API for text and modeled input channels.",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3417",
            "http://localhost:3417",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type"],
    )

    resolved_path = database_path or Path(
        os.environ.get("AAT_WORKBENCH_DB", "out/workbench.db")
    )
    store = RunStore(resolved_path)
    target_store = TargetStore(resolved_path)
    engine = VoiceAssessmentEngine(reviewer=reviewer_from_environment())

    if not target_store.list():
        target_store.create(
            TargetProfileInput(
                name="Local Simulator",
                environment="simulation",
                connector="simulator",
            )
        )

    def require_target(target_id: str) -> TargetProfile:
        target = target_store.get(target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="target not found")
        if not target.enabled:
            raise HTTPException(status_code=409, detail="target is disabled")
        return target

    def require_production_acknowledgement(
        target: TargetProfile, acknowledged: bool
    ) -> None:
        if (
            target.environment == "production" or target.connector == "device-bridge"
        ) and not acknowledged:
            raise HTTPException(
                status_code=409,
                detail=(
                    "production and hardware targets require explicit acknowledgement "
                    "for this run"
                ),
            )

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "network": "loopback", "storage": "sqlite"}

    @app.get("/api/providers")
    async def providers() -> dict:
        return {
            "providers": [
                {
                    "id": "simulated",
                    "label": "Simulator",
                    "capabilities": [
                        "text_input",
                        "modeled_channel_input",
                        "transcript_output",
                    ],
                }
            ]
        }

    @app.get("/api/targets")
    async def list_targets() -> dict:
        return {"targets": [target.model_dump() for target in target_store.list()]}

    @app.post("/api/targets", status_code=201)
    async def create_target(request: TargetProfileInput) -> dict:
        return target_store.create(request).model_dump()

    @app.get("/api/targets/{target_id}")
    async def get_target(target_id: str) -> dict:
        target = target_store.get(target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="target not found")
        return target.model_dump()

    @app.put("/api/targets/{target_id}")
    async def update_target(target_id: str, request: TargetProfileInput) -> dict:
        target = target_store.update(target_id, request)
        if target is None:
            raise HTTPException(status_code=404, detail="target not found")
        return target.model_dump()

    @app.delete("/api/targets/{target_id}", status_code=204)
    async def delete_target(target_id: str) -> None:
        target = target_store.get(target_id)
        if target is None:
            raise HTTPException(status_code=404, detail="target not found")
        if target.connector == "simulator":
            raise HTTPException(status_code=409, detail="the local simulator cannot be deleted")
        if not target_store.delete(target_id):
            raise HTTPException(status_code=404, detail="target not found")

    @app.post("/api/targets/{target_id}/preview")
    async def preview_target_request(
        target_id: str, request: ChannelRunRequest
    ) -> dict:
        target = require_target(target_id)
        message = encode_channel(request.adapter, request.fields)
        try:
            wire_request = preview_target(target, message)
        except ConnectorError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "target": {
                "id": target.id,
                "name": target.name,
                "environment": target.environment,
                "connector": target.connector,
            },
            "message": {
                "msg_id": message.msg_id,
                "topic": message.topic,
                "body": public_message_body(message.body),
            },
            "wire_request": wire_request,
        }

    @app.post("/api/repeater/runs")
    async def create_repeater_run(request: RepeaterRequest) -> dict:
        result = await engine.run(request.script, mode="repeater")
        return store.save(result)

    @app.post("/api/intruder/runs")
    async def create_intruder_run(request: IntruderRequest) -> dict:
        semaphore = asyncio.Semaphore(request.concurrency)

        async def execute(index: int, payload: str) -> dict:
            async with semaphore:
                script = request.template.replace(INSERTION_MARKER, payload)
                result = await engine.run(script, mode="intruder")
                stored = store.save(result)
                return {"case_index": index, "payload": payload, "result": stored}

        cases = await asyncio.gather(
            *(execute(index, payload) for index, payload in enumerate(request.payloads))
        )
        confirmed = sum(
            case["result"]["analysis"]["verdict"] == "confirmed_violation"
            for case in cases
        )
        return {
            "case_count": len(cases),
            "confirmed_violations": confirmed,
            "cases": cases,
        }

    @app.post("/api/channel/runs")
    async def create_channel_run(request: ChannelRunRequest) -> dict:
        message = encode_channel(request.adapter, request.fields)
        encoded_input = json.dumps(
            {"topic": message.topic, "body": public_message_body(message.body)},
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        result = await engine.run(encoded_input, mode="channel")
        stored = store.save(result)
        return {
            "adapter": request.adapter,
            "message": {
                "msg_id": message.msg_id,
                "topic": message.topic,
                "body": public_message_body(message.body),
            },
            "result": stored,
        }

    @app.post("/api/workbench/runs")
    async def create_target_run(request: TargetRunRequest) -> dict:
        target = require_target(request.target_id)
        require_production_acknowledgement(target, request.production_acknowledged)
        message = encode_channel(request.adapter, request.fields)
        try:
            if target.connector == "simulator":
                encoded_input = json.dumps(
                    {
                        "topic": message.topic,
                        "body": public_message_body(message.body),
                    },
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                result = await engine.run(encoded_input, mode="workbench")
                result = replace(
                    result,
                    metadata={
                        "target": {
                            "id": target.id,
                            "name": target.name,
                            "environment": target.environment,
                            "connector": target.connector,
                        },
                        "channel": {
                            "adapter": request.adapter,
                            "message_id": message.msg_id,
                            "topic": message.topic,
                            "body": public_message_body(message.body),
                        },
                        "exchange": {
                            "wire_request": preview_target(target, message),
                        },
                    },
                )
            else:
                result = await run_production_target(
                    target, request.adapter, request.fields, mode="workbench"
                )
        except ConnectorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return store.save(result)

    @app.post("/api/campaigns/runs")
    async def create_target_campaign(request: TargetBatchRequest) -> dict:
        target = require_target(request.target_id)
        require_production_acknowledgement(target, request.production_acknowledged)
        concurrency = (
            1
            if target.environment == "production" or target.connector == "device-bridge"
            else request.concurrency
        )
        semaphore = asyncio.Semaphore(concurrency)

        async def execute(index: int, payload: str) -> dict:
            fields = replace_marker(request.fields_template, payload)
            async with semaphore:
                nested_request = TargetRunRequest(
                    target_id=target.id,
                    adapter=request.adapter,
                    fields=fields,
                    production_acknowledged=request.production_acknowledged,
                )
                result_dict = await create_target_run(nested_request)
                return {"case_index": index, "payload": payload, "result": result_dict}

        cases = await asyncio.gather(
            *(execute(index, payload) for index, payload in enumerate(request.payloads))
        )
        return {
            "case_count": len(cases),
            "confirmed_violations": sum(
                case["result"]["analysis"]["verdict"] == "confirmed_violation"
                for case in cases
            ),
            "effective_concurrency": concurrency,
            "cases": cases,
        }

    @app.get("/api/runs")
    async def list_runs(limit: int = Query(default=50, ge=1, le=100)) -> dict:
        return {"runs": store.list(limit)}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        result = store.get(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.get("/api/runs/{run_id}/audio")
    async def get_run_audio(run_id: str) -> Response:
        artifact = store.get_audio(run_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="audio artifact not found")
        media_type, content = artifact
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "private, no-store"},
        )

    return app


app = create_app()
