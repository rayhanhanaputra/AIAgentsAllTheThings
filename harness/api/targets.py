"""Production target profiles and local persistence.

Profiles contain connection contracts and *references* to secret environment
variables. Secret values are intentionally never accepted or persisted.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

SECRET_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
HARDWARE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}$")


class EvidenceRules(BaseModel):
    response_markers: List[str] = Field(default_factory=list, max_length=20)
    forbidden_tools: List[str] = Field(default_factory=list, max_length=50)

    @field_validator("response_markers", "forbidden_tools")
    @classmethod
    def rules_are_bounded(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 256 for item in cleaned):
            raise ValueError("evidence rules must be 1-256 characters")
        return cleaned


class TargetProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    environment: Literal["simulation", "staging", "production"]
    connector: Literal[
        "simulator",
        "http",
        "tcp",
        "mqtt",
        "websocket",
        "voice",
        "voice-stream",
        "optical",
        "device-bridge",
    ]
    enabled: bool = True

    endpoint: Optional[str] = Field(default=None, max_length=2048)
    method: Literal["POST", "PUT", "PATCH"] = "POST"
    headers: Dict[str, str] = Field(default_factory=dict)
    secret_headers: Dict[str, str] = Field(default_factory=dict)
    request_template: str = Field(
        default='{"input":"{{input}}"}', min_length=2, max_length=10_000
    )
    response_path: Optional[str] = Field(default=None, max_length=256)
    actions_path: Optional[str] = Field(default=None, max_length=256)

    mapper_enabled: bool = False
    mapper_endpoint: Optional[str] = Field(default=None, max_length=2048)
    mapper_model: Optional[str] = Field(default=None, max_length=200)
    mapper_api_key_env: Optional[str] = Field(default=None, max_length=128)
    mapper_instructions: str = Field(default="", max_length=8_000)
    mapper_required_keys: List[str] = Field(default_factory=list, max_length=50)
    mapper_timeout_seconds: float = Field(default=20, ge=1, le=60)

    response_mapper_enabled: bool = False
    response_mapper_endpoint: Optional[str] = Field(default=None, max_length=2048)
    response_mapper_model: Optional[str] = Field(default=None, max_length=200)
    response_mapper_api_key_env: Optional[str] = Field(default=None, max_length=128)
    response_mapper_instructions: str = Field(default="", max_length=8_000)
    response_mapper_timeout_seconds: float = Field(default=20, ge=1, le=60)

    host: Optional[str] = Field(default=None, max_length=253)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    tcp_raw: bool = False

    mqtt_publish_topic: Optional[str] = Field(default=None, max_length=512)
    mqtt_response_topic: Optional[str] = Field(default=None, max_length=512)
    mqtt_qos: Literal[0, 1] = 1
    mqtt_tls: bool = False
    mqtt_username_env: Optional[str] = Field(default=None, max_length=128)
    mqtt_password_env: Optional[str] = Field(default=None, max_length=128)

    voice_response_audio_path: Optional[str] = Field(default=None, max_length=256)
    voice_response_audio_type: Literal[
        "audio/wav", "audio/mpeg", "audio/ogg", "audio/webm", "audio/mp4", "audio/flac"
    ] = "audio/wav"
    voice_stream_chunk_template: str = Field(
        default='{"type":"audio.chunk","audio":"{{audio_chunk_base64}}"}',
        min_length=2,
        max_length=10_000,
    )
    voice_stream_end_template: str = Field(
        default='{"type":"audio.end"}', min_length=2, max_length=10_000
    )
    voice_stream_cancel_template: str = Field(
        default='{"type":"session.cancel"}', min_length=2, max_length=10_000
    )
    voice_stream_done_path: str = Field(default="type", min_length=1, max_length=256)
    voice_stream_done_value: str = Field(
        default="session.done", min_length=1, max_length=256
    )
    voice_stream_chunk_bytes: int = Field(default=16_384, ge=1_024, le=65_536)
    voice_stream_max_events: int = Field(default=100, ge=1, le=500)

    hardware_kind: Literal["ble", "nfc", "gpio"] = "ble"
    hardware_operation: Literal[
        "ble_advertise", "nfc_emulate", "gpio_sequence"
    ] = "ble_advertise"
    hardware_device_id: Optional[str] = Field(default=None, max_length=128)
    hardware_allowed_device_ids: List[str] = Field(default_factory=list, max_length=20)
    hardware_resource: Optional[str] = Field(default=None, max_length=128)
    hardware_allowed_resources: List[str] = Field(default_factory=list, max_length=50)
    hardware_duration_ms: int = Field(default=5_000, ge=100, le=30_000)
    hardware_stop_endpoint: Optional[str] = Field(default=None, max_length=2048)
    hardware_stop_template: str = Field(
        default=(
            '{"device_id":"{{device_id}}","operation":"{{operation}}",'
            '"resource":"{{resource}}","reason":"assessment_complete"}'
        ),
        min_length=2,
        max_length=10_000,
    )

    timeout_seconds: float = Field(default=20, ge=1, le=60)
    evidence: EvidenceRules = Field(default_factory=EvidenceRules)

    @field_validator("name")
    @classmethod
    def name_is_clean(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("headers")
    @classmethod
    def headers_are_bounded(cls, value: Dict[str, str]) -> Dict[str, str]:
        if len(value) > 30:
            raise ValueError("use no more than 30 static headers")
        blocked = {
            "host",
            "content-length",
            "transfer-encoding",
            "connection",
            "authorization",
            "proxy-authorization",
            "x-api-key",
            "api-key",
            "cookie",
            "set-cookie",
        }
        for key, item in value.items():
            if key.lower() in blocked:
                raise ValueError(f"header '{key}' is managed by the connector")
            if not key.strip() or len(key) > 128 or len(item) > 2_000:
                raise ValueError("header names and values exceed their limits")
        return value

    @field_validator("secret_headers")
    @classmethod
    def secret_references_are_safe(cls, value: Dict[str, str]) -> Dict[str, str]:
        if len(value) > 10:
            raise ValueError("use no more than 10 secret headers")
        blocked = {"host", "content-length", "transfer-encoding", "connection"}
        for header, env_name in value.items():
            if (
                not header.strip()
                or len(header) > 128
                or header.lower() in blocked
            ):
                raise ValueError("secret header name is invalid")
            if not SECRET_ENV_PATTERN.fullmatch(env_name):
                raise ValueError("secret values must reference an uppercase environment variable")
        return value

    @field_validator(
        "response_path",
        "actions_path",
        "voice_response_audio_path",
        "voice_stream_done_path",
    )
    @classmethod
    def paths_are_simple(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        if not all(FIELD_PATTERN.fullmatch(part) for part in value.split(".")):
            raise ValueError("response paths use dot-separated field names")
        return value

    @field_validator("mqtt_publish_topic", "mqtt_response_topic")
    @classmethod
    def mqtt_topics_are_exact(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        topic = value.strip()
        if not topic or "\x00" in topic or "+" in topic or "#" in topic:
            raise ValueError("MQTT topics must be exact and cannot contain wildcards")
        return topic

    @field_validator("mqtt_username_env", "mqtt_password_env")
    @classmethod
    def mqtt_secret_references_are_safe(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return None
        if not SECRET_ENV_PATTERN.fullmatch(value):
            raise ValueError("MQTT credentials must reference an uppercase environment variable")
        return value

    @field_validator("mapper_api_key_env", "response_mapper_api_key_env")
    @classmethod
    def mapper_secret_reference_is_safe(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return None
        if not SECRET_ENV_PATTERN.fullmatch(value):
            raise ValueError("mapper API keys must reference an uppercase environment variable")
        return value

    @field_validator("mapper_required_keys")
    @classmethod
    def mapper_keys_are_safe(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value]
        if any(not FIELD_PATTERN.fullmatch(item) for item in cleaned):
            raise ValueError("mapper required keys must be simple field names")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("mapper required keys cannot contain duplicates")
        return cleaned

    @field_validator(
        "hardware_allowed_device_ids", "hardware_allowed_resources"
    )
    @classmethod
    def hardware_allowlists_are_exact(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value]
        if any(not HARDWARE_ID_PATTERN.fullmatch(item) for item in cleaned):
            raise ValueError("hardware allowlists contain an invalid identifier")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("hardware allowlists cannot contain duplicates")
        return cleaned

    @field_validator("hardware_device_id", "hardware_resource")
    @classmethod
    def hardware_identifiers_are_safe(cls, value: Optional[str]) -> Optional[str]:
        if value in {None, ""}:
            return None
        if not HARDWARE_ID_PATTERN.fullmatch(value):
            raise ValueError("hardware identifier is invalid")
        return value

    @model_validator(mode="after")
    def connector_configuration_matches(self) -> "TargetProfileInput":
        if self.mapper_enabled:
            if self.connector == "simulator":
                raise ValueError("input mapping agents require a real target connector")
            if not self.mapper_endpoint or not self.mapper_model or not self.mapper_api_key_env:
                raise ValueError("input mapping agents require endpoint, model, and API key environment variable")
            parsed_mapper = urlsplit(self.mapper_endpoint)
            if parsed_mapper.scheme not in {"http", "https"} or not parsed_mapper.hostname:
                raise ValueError("mapper endpoint must be an absolute HTTP(S) URL")
            if parsed_mapper.username or parsed_mapper.password or parsed_mapper.fragment:
                raise ValueError("mapper endpoint cannot contain credentials or a fragment")
            if parsed_mapper.scheme == "http" and parsed_mapper.hostname not in {
                "localhost", "127.0.0.1", "::1"
            }:
                raise ValueError("non-loopback mapper endpoints must use HTTPS")
            if not self.mapper_instructions.strip():
                raise ValueError("input mapping agents require mapping instructions")
            if "{{mapped}}" not in self.request_template:
                raise ValueError("mapper-enabled request templates must contain {{mapped}}")
        if self.response_mapper_enabled:
            if self.connector == "simulator":
                raise ValueError("response mapping agents require a real target connector")
            if (
                not self.response_mapper_endpoint
                or not self.response_mapper_model
                or not self.response_mapper_api_key_env
            ):
                raise ValueError(
                    "response mapping agents require endpoint, model, and API key environment variable"
                )
            parsed_response_mapper = urlsplit(self.response_mapper_endpoint)
            if (
                parsed_response_mapper.scheme not in {"http", "https"}
                or not parsed_response_mapper.hostname
            ):
                raise ValueError("response mapper endpoint must be an absolute HTTP(S) URL")
            if (
                parsed_response_mapper.username
                or parsed_response_mapper.password
                or parsed_response_mapper.fragment
            ):
                raise ValueError(
                    "response mapper endpoint cannot contain credentials or a fragment"
                )
            if (
                parsed_response_mapper.scheme == "http"
                and parsed_response_mapper.hostname
                not in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("non-loopback response mapper endpoints must use HTTPS")
        if self.connector == "simulator":
            if self.environment != "simulation":
                raise ValueError("simulator targets must use the simulation environment")
            return self
        if self.connector == "http":
            if not self.endpoint:
                raise ValueError("HTTP targets require an endpoint")
            parsed = urlsplit(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("endpoint must be an absolute HTTP(S) URL")
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError("endpoint cannot contain credentials or a fragment")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("non-loopback HTTP targets must use HTTPS")
            try:
                json.loads(self.request_template)
            except json.JSONDecodeError as exc:
                raise ValueError("request template must be valid JSON") from exc
            return self
        if self.connector == "websocket":
            if not self.endpoint:
                raise ValueError("WebSocket targets require an endpoint")
            parsed = urlsplit(self.endpoint)
            if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
                raise ValueError("endpoint must be an absolute WebSocket URL")
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError("endpoint cannot contain credentials or a fragment")
            if parsed.scheme == "ws" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("non-loopback WebSocket targets must use WSS")
            try:
                json.loads(self.request_template)
            except json.JSONDecodeError as exc:
                raise ValueError("request template must be valid JSON") from exc
            return self
        if self.connector == "voice":
            if not self.endpoint:
                raise ValueError("voice targets require an endpoint")
            parsed = urlsplit(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("endpoint must be an absolute HTTP(S) URL")
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError("endpoint cannot contain credentials or a fragment")
            if parsed.scheme == "http" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("non-loopback voice targets must use HTTPS")
            if not self.response_path and not self.response_mapper_enabled:
                raise ValueError(
                    "voice targets require a transcript response path or response mapper"
                )
            try:
                json.loads(self.request_template)
            except json.JSONDecodeError as exc:
                raise ValueError("request template must be valid JSON") from exc
            return self
        if self.connector == "voice-stream":
            if not self.endpoint:
                raise ValueError("streaming voice targets require an endpoint")
            parsed = urlsplit(self.endpoint)
            if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
                raise ValueError("endpoint must be an absolute WebSocket URL")
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError("endpoint cannot contain credentials or a fragment")
            if parsed.scheme == "ws" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("non-loopback streaming voice targets must use WSS")
            if not self.response_path and not self.response_mapper_enabled:
                raise ValueError(
                    "streaming voice targets require a transcript path or response mapper"
                )
            for template in (
                self.request_template,
                self.voice_stream_chunk_template,
                self.voice_stream_end_template,
                self.voice_stream_cancel_template,
            ):
                try:
                    json.loads(template)
                except json.JSONDecodeError as exc:
                    raise ValueError("voice stream templates must be valid JSON") from exc
            return self
        if self.connector == "optical":
            if not self.endpoint:
                raise ValueError("optical targets require an endpoint")
            parsed = urlsplit(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("endpoint must be an absolute HTTP(S) URL")
            if parsed.username or parsed.password or parsed.fragment:
                raise ValueError("endpoint cannot contain credentials or a fragment")
            if parsed.scheme == "http" and parsed.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("non-loopback optical targets must use HTTPS")
            if not self.response_path and not self.response_mapper_enabled:
                raise ValueError(
                    "optical targets require a response text path or response mapper"
                )
            try:
                json.loads(self.request_template)
            except json.JSONDecodeError as exc:
                raise ValueError("request template must be valid JSON") from exc
            return self
        if self.connector == "device-bridge":
            if not self.endpoint or not self.hardware_stop_endpoint:
                raise ValueError("device bridges require action and stop endpoints")
            action_url = urlsplit(self.endpoint)
            stop_url = urlsplit(self.hardware_stop_endpoint)
            for label, parsed in (("action", action_url), ("stop", stop_url)):
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError(f"hardware {label} endpoint must be HTTP(S)")
                if parsed.username or parsed.password or parsed.fragment:
                    raise ValueError("hardware endpoints cannot contain credentials or fragments")
                if parsed.scheme == "http" and parsed.hostname not in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }:
                    raise ValueError("non-loopback hardware bridges must use HTTPS")
            if (action_url.scheme, action_url.netloc) != (
                stop_url.scheme,
                stop_url.netloc,
            ):
                raise ValueError("hardware action and stop endpoints must share an origin")
            expected_operation = {
                "ble": "ble_advertise",
                "nfc": "nfc_emulate",
                "gpio": "gpio_sequence",
            }[self.hardware_kind]
            if self.hardware_operation != expected_operation:
                raise ValueError("hardware operation does not match the selected device kind")
            if (
                not self.hardware_device_id
                or self.hardware_device_id not in self.hardware_allowed_device_ids
            ):
                raise ValueError("selected hardware device must be explicitly allowlisted")
            if (
                not self.hardware_resource
                or self.hardware_resource not in self.hardware_allowed_resources
            ):
                raise ValueError("selected hardware resource must be explicitly allowlisted")
            for template in (self.request_template, self.hardware_stop_template):
                try:
                    json.loads(template)
                except json.JSONDecodeError as exc:
                    raise ValueError("hardware bridge templates must be valid JSON") from exc
            return self
        if self.connector == "tcp":
            if not self.host or not self.port:
                raise ValueError("TCP targets require a host and port")
            return self
        if self.connector == "mqtt":
            if not self.host or not self.port:
                raise ValueError("MQTT targets require a broker host and port")
            if not self.mqtt_publish_topic or not self.mqtt_response_topic:
                raise ValueError("MQTT targets require publish and response topics")
            try:
                json.loads(self.request_template)
            except json.JSONDecodeError as exc:
                raise ValueError("request template must be valid JSON") from exc
            return self
        return self


class TargetProfile(TargetProfileInput):
    id: str
    created_at: str
    updated_at: str


class TargetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS target_profiles (
                    id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, value: TargetProfileInput) -> TargetProfile:
        now = datetime.now(timezone.utc).isoformat()
        profile = TargetProfile(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            **value.model_dump(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO target_profiles(id, profile_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (profile.id, profile.model_dump_json(), now, now),
            )
        return profile

    def list(self) -> List[TargetProfile]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT profile_json FROM target_profiles ORDER BY updated_at DESC"
            ).fetchall()
        return [TargetProfile.model_validate_json(row["profile_json"]) for row in rows]

    def get(self, target_id: str) -> Optional[TargetProfile]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT profile_json FROM target_profiles WHERE id = ?", (target_id,)
            ).fetchone()
        return TargetProfile.model_validate_json(row["profile_json"]) if row else None

    def update(self, target_id: str, value: TargetProfileInput) -> Optional[TargetProfile]:
        existing = self.get(target_id)
        if existing is None:
            return None
        profile = TargetProfile(
            id=target_id,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            **value.model_dump(),
        )
        with self._connect() as connection:
            connection.execute(
                "UPDATE target_profiles SET profile_json = ?, updated_at = ? WHERE id = ?",
                (profile.model_dump_json(), profile.updated_at, target_id),
            )
        return profile

    def delete(self, target_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM target_profiles WHERE id = ?", (target_id,)
            )
        return cursor.rowcount > 0
