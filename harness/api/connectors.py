"""Bounded server-side connectors for real target agents."""

from __future__ import annotations

import base64
import binascii
import copy
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urlsplit

from harness.core.types import Message

from .targets import TargetProfile

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - exercised only in minimal installations.
    mqtt = None

try:
    from websockets.exceptions import WebSocketException
    from websockets.sync.client import connect as websocket_connect
except ImportError:  # pragma: no cover - exercised only in minimal installations.
    WebSocketException = Exception
    websocket_connect = None

MAX_REQUEST_BYTES = 64 * 1024
MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
MAX_TCP_RESPONSE_BYTES = 64 * 1024
MAX_VOICE_AUDIO_BYTES = 6 * 1024 * 1024
MAX_VOICE_RESPONSE_BYTES = 9 * 1024 * 1024


class ConnectorError(RuntimeError):
    """A safe user-facing connector error."""


@dataclass(frozen=True)
class ObservedAction:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetExchange:
    connector: str
    destination: str
    wire_request: Dict[str, Any]
    response_metadata: Dict[str, Any]
    raw_response: str
    response_text: str
    actions: List[ObservedAction]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Connector(Protocol):
    """Server-side plugin contract for bounded target delivery."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]: ...

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange: ...


def perceived_input(message: Message) -> str:
    for key in ("prompt", "transcript", "scanned_text", "context", "advertised"):
        value = message.body.get(key)
        if isinstance(value, str) and value:
            return value
    return json.dumps(message.body, ensure_ascii=False, separators=(",", ":"))


def _replace_placeholders(
    value: Any, message: Message, extras: Optional[Dict[str, Any]] = None
) -> Any:
    input_text = perceived_input(message)
    public_body = {
        key: item for key, item in message.body.items() if key != "_aat_mapper_output"
    }
    envelope = {"msg_id": message.msg_id, "topic": message.topic, "body": public_body}
    if isinstance(value, str):
        if extras and value in extras:
            return extras[value]
        if value == "{{input}}":
            return input_text
        if value == "{{body}}":
            return message.body
        if value == "{{message}}":
            return envelope
        if value == "{{mapped}}":
            if "_aat_mapper_output" not in message.body:
                raise ConnectorError("mapped request is unavailable")
            return message.body["_aat_mapper_output"]
        if value == "{{audio_base64}}":
            return message.body.get("audio_base64", "")
        if value == "{{audio_mime_type}}":
            return message.body.get("audio_mime_type", "")
        if value == "{{audio_filename}}":
            return message.body.get("audio_filename", "")
        if value == "{{image_base64}}":
            return message.body.get("image_base64", "")
        if value == "{{image_mime_type}}":
            return message.body.get("image_mime_type", "")
        if value == "{{image_filename}}":
            return message.body.get("image_filename", "")
        rendered = value.replace("{{input}}", input_text).replace(
            "{{message_id}}", message.msg_id
        )
        if extras:
            for placeholder, replacement in extras.items():
                if isinstance(replacement, str):
                    rendered = rendered.replace(placeholder, replacement)
        return rendered
    if isinstance(value, list):
        return [_replace_placeholders(item, message, extras) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_placeholders(item, message, extras)
            for key, item in value.items()
        }
    return value


def render_request(
    profile: TargetProfile, message: Message, max_bytes: int = MAX_REQUEST_BYTES
) -> Any:
    try:
        template = json.loads(profile.request_template)
    except json.JSONDecodeError as exc:  # Profiles are validated, retained for defense in depth.
        raise ConnectorError("target request template is invalid") from exc
    rendered = _replace_placeholders(template, message)
    encoded = json.dumps(rendered, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > max_bytes:
        raise ConnectorError(f"rendered request exceeds {max_bytes} bytes")
    return rendered


def render_template(
    template: str,
    message: Message,
    *,
    max_bytes: int,
    extras: Optional[Dict[str, Any]] = None,
) -> Any:
    try:
        parsed = json.loads(template)
    except json.JSONDecodeError as exc:
        raise ConnectorError("connector event template is invalid") from exc
    rendered = _replace_placeholders(parsed, message, extras)
    encoded = json.dumps(rendered, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > max_bytes:
        raise ConnectorError(f"rendered event exceeds {max_bytes} bytes")
    return rendered


def _redact_exact(value: Any, secret_value: str, replacement: str) -> Any:
    if isinstance(value, str):
        return replacement if value == secret_value else value
    if isinstance(value, list):
        return [_redact_exact(item, secret_value, replacement) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_exact(item, secret_value, replacement)
            for key, item in value.items()
        }
    return value


def _replace_path(value: Any, path: Optional[str], replacement: Any) -> Any:
    cloned = copy.deepcopy(value)
    if not path:
        return cloned
    current = cloned
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return cloned
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        current[parts[-1]] = replacement
    return cloned


def _resolve_destination(host: str, port: int, *, public_allowed: bool) -> str:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConnectorError(f"cannot resolve target host '{host}'") from exc
    addresses = []
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if address.is_unspecified or address.is_multicast or address.is_link_local or address.is_reserved:
            raise ConnectorError("target resolves to a prohibited network address")
        if not public_allowed and not (address.is_loopback or address.is_private):
            raise ConnectorError("raw TCP targets are limited to loopback or private networks")
        addresses.append(str(address))
    if not addresses:
        raise ConnectorError("target host has no usable address")
    return sorted(set(addresses))[0]


def _extract_path(value: Any, path: Optional[str]) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _parse_observation(
    raw: str, response_path: Optional[str], actions_path: Optional[str]
) -> tuple[str, List[ObservedAction]]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return raw, []
    extracted = _extract_path(decoded, response_path)
    if extracted is None:
        response_text = raw
    elif isinstance(extracted, str):
        response_text = extracted
    else:
        response_text = json.dumps(extracted, ensure_ascii=False)
    actions: List[ObservedAction] = []
    action_values = _extract_path(decoded, actions_path) if actions_path else None
    if isinstance(action_values, list):
        for item in action_values[:100]:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("tool")
            arguments = item.get("arguments") or item.get("args") or {}
            if isinstance(name, str) and isinstance(arguments, dict):
                actions.append(ObservedAction(name=name[:256], arguments=arguments))
    return response_text[:MAX_HTTP_RESPONSE_BYTES], actions


def _json_or_text(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _observation_without_media(value: Dict[str, Any]) -> Dict[str, Any]:
    safe = copy.deepcopy(value)
    for phase in ("before", "after"):
        observation = safe.get(phase)
        if isinstance(observation, dict) and observation.get("screenshot_data_url"):
            observation["screenshot_data_url"] = "<screenshot stored separately>"
    return safe


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float) -> None:
        super().__init__(
            host,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


class HttpConnector:
    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        body = render_request(profile, message)
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            headers[header] = f"<secret:{env_name}>"
        return {
            "method": profile.method,
            "url": profile.endpoint,
            "headers": headers,
            "body": body,
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if not profile.endpoint:
            raise ConnectorError("HTTP target endpoint is missing")
        parsed = urlsplit(profile.endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
        body = render_request(profile, message)
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            secret = os.environ.get(env_name)
            if secret is None:
                raise ConnectorError(f"required secret environment variable '{env_name}' is not set")
            headers[header] = secret
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection_type = (
            _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        )
        connection = connection_type(
            parsed.hostname or "", pinned_ip, port, profile.timeout_seconds
        )
        try:
            connection.request(profile.method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ConnectorError("target redirects are not followed")
            payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(payload) > MAX_HTTP_RESPONSE_BYTES:
                raise ConnectorError("target response exceeds 1 MiB")
            raw = payload.decode("utf-8", errors="replace")
            response_text, actions = _parse_observation(
                raw, profile.response_path, profile.actions_path
            )
            metadata = {
                "status": response.status,
                "reason": response.reason,
                "content_type": response.getheader("Content-Type"),
            }
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise ConnectorError(f"HTTP target connection failed: {exc}") from exc
        finally:
            connection.close()
        return TargetExchange(
            connector="http",
            destination=profile.endpoint,
            wire_request=self.preview(profile, message),
            response_metadata=metadata,
            raw_response=raw,
            response_text=response_text,
            actions=actions,
        )


class TcpConnector:
    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        rendered = render_request(profile, message)
        payload = perceived_input(message) if profile.tcp_raw else json.dumps(rendered, ensure_ascii=False)
        return {
            "host": profile.host,
            "port": profile.port,
            "framing": "line",
            "mode": "raw" if profile.tcp_raw else "json",
            "payload": payload + "\n",
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if not profile.host or not profile.port:
            raise ConnectorError("TCP target host or port is missing")
        address = _resolve_destination(profile.host, profile.port, public_allowed=False)
        preview = self.preview(profile, message)
        payload = str(preview["payload"]).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise ConnectorError("rendered request exceeds 64 KiB")
        chunks: List[bytes] = []
        try:
            with socket.create_connection(
                (address, profile.port), timeout=profile.timeout_seconds
            ) as connection:
                connection.settimeout(profile.timeout_seconds)
                connection.sendall(payload)
                while sum(len(chunk) for chunk in chunks) <= MAX_TCP_RESPONSE_BYTES:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except socket.timeout:
            pass
        except OSError as exc:
            raise ConnectorError(f"TCP target connection failed: {exc}") from exc
        response = b"".join(chunks)
        if len(response) > MAX_TCP_RESPONSE_BYTES:
            raise ConnectorError("TCP target response exceeds 64 KiB")
        raw = response.decode("utf-8", errors="replace")
        response_text, actions = _parse_observation(
            raw, profile.response_path, profile.actions_path
        )
        return TargetExchange(
            connector="tcp",
            destination=f"{profile.host}:{profile.port}",
            wire_request=preview,
            response_metadata={"bytes": len(response)},
            raw_response=raw,
            response_text=response_text,
            actions=actions,
        )


class MqttConnector:
    """Publish one bounded request and await one response on an exact topic."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        rendered = render_request(profile, message)
        response_topic = (profile.mqtt_response_topic or "").replace(
            "{{message_id}}", message.msg_id
        )
        publish_topic = (profile.mqtt_publish_topic or "").replace(
            "{{message_id}}", message.msg_id
        )
        return {
            "broker": f"{profile.host}:{profile.port}",
            "tls": profile.mqtt_tls,
            "qos": profile.mqtt_qos,
            "retain": False,
            "publish_topic": publish_topic,
            "response_topic": response_topic,
            "username": (
                f"<secret:{profile.mqtt_username_env}>"
                if profile.mqtt_username_env
                else None
            ),
            "password": (
                f"<secret:{profile.mqtt_password_env}>"
                if profile.mqtt_password_env
                else None
            ),
            "payload": rendered,
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if mqtt is None:
            raise ConnectorError("MQTT connector requires the paho-mqtt package")
        if not profile.host or not profile.port:
            raise ConnectorError("MQTT broker host or port is missing")

        address = _resolve_destination(profile.host, profile.port, public_allowed=False)
        preview = self.preview(profile, message)
        publish_topic = str(preview["publish_topic"])
        response_topic = str(preview["response_topic"])
        payload = json.dumps(
            preview["payload"], ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
        if len(payload) > MAX_REQUEST_BYTES:
            raise ConnectorError("rendered request exceeds 64 KiB")

        username = self._resolve_secret(profile.mqtt_username_env)
        password = self._resolve_secret(profile.mqtt_password_env)
        if password is not None and username is None:
            raise ConnectorError("MQTT password requires a configured username")

        connected = threading.Event()
        subscribed = threading.Event()
        response_received = threading.Event()
        failures: List[str] = []
        response_payload: List[bytes] = []
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"aat-{uuid.uuid4().hex[:16]}",
            protocol=mqtt.MQTTv311,
        )
        if username is not None:
            client.username_pw_set(username, password)
        if profile.mqtt_tls:
            client.tls_set_context(ssl.create_default_context())

        def on_connect(client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
            if getattr(reason_code, "is_failure", bool(reason_code)):
                failures.append(f"broker rejected connection: {reason_code}")
                connected.set()
                return
            result, _mid = client.subscribe(response_topic, qos=profile.mqtt_qos)
            if result != mqtt.MQTT_ERR_SUCCESS:
                failures.append("cannot subscribe to MQTT response topic")
                subscribed.set()
            connected.set()

        def on_subscribe(
            _client: Any,
            _userdata: Any,
            _mid: int,
            reason_codes: Any,
            _properties: Any,
        ) -> None:
            if reason_codes and any(
                getattr(code, "is_failure", False) for code in reason_codes
            ):
                failures.append("broker rejected MQTT response subscription")
            subscribed.set()

        def on_message(_client: Any, _userdata: Any, received: Any) -> None:
            data = bytes(received.payload)
            if len(data) > MAX_HTTP_RESPONSE_BYTES:
                failures.append("MQTT response exceeds 1 MiB")
            else:
                response_payload.append(data)
            response_received.set()

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        loop_started = False
        try:
            result = client.connect(
                address,
                profile.port,
                keepalive=max(10, min(60, int(profile.timeout_seconds * 2))),
            )
            if result != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectorError(f"MQTT connection failed with code {result}")
            client.loop_start()
            loop_started = True
            if not connected.wait(profile.timeout_seconds):
                raise ConnectorError("MQTT broker connection timed out")
            if failures:
                raise ConnectorError(failures[0])
            if not subscribed.wait(profile.timeout_seconds):
                raise ConnectorError("MQTT response subscription timed out")
            if failures:
                raise ConnectorError(failures[0])
            publication = client.publish(
                publish_topic,
                payload,
                qos=profile.mqtt_qos,
                retain=False,
            )
            if publication.rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectorError(f"MQTT publish failed with code {publication.rc}")
            publication.wait_for_publish(timeout=profile.timeout_seconds)
            if not publication.is_published():
                raise ConnectorError("MQTT publish acknowledgement timed out")
            if not response_received.wait(profile.timeout_seconds):
                raise ConnectorError("MQTT response timed out")
            if failures:
                raise ConnectorError(failures[0])
        except ConnectorError:
            raise
        except (OSError, ValueError) as exc:
            raise ConnectorError(f"MQTT target connection failed: {exc}") from exc
        finally:
            if loop_started:
                client.disconnect()
                client.loop_stop()

        raw_bytes = response_payload[0] if response_payload else b""
        raw = raw_bytes.decode("utf-8", errors="replace")
        response_text, actions = _parse_observation(
            raw, profile.response_path, profile.actions_path
        )
        return TargetExchange(
            connector="mqtt",
            destination=f"{profile.host}:{profile.port}",
            wire_request=preview,
            response_metadata={
                "bytes": len(raw_bytes),
                "qos": profile.mqtt_qos,
                "response_topic": response_topic,
            },
            raw_response=raw,
            response_text=response_text,
            actions=actions,
        )

    @staticmethod
    def _resolve_secret(env_name: Optional[str]) -> Optional[str]:
        if not env_name:
            return None
        value = os.environ.get(env_name)
        if value is None:
            raise ConnectorError(
                f"required secret environment variable '{env_name}' is not set"
            )
        return value


class WebSocketConnector:
    """Send one JSON message and capture one bounded WebSocket response."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        headers = dict(profile.headers)
        for header, env_name in profile.secret_headers.items():
            headers[header] = f"<secret:{env_name}>"
        return {
            "url": profile.endpoint,
            "headers": headers,
            "message_type": "text/json",
            "payload": render_request(profile, message),
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if websocket_connect is None:
            raise ConnectorError("WebSocket connector requires the websockets package")
        if not profile.endpoint:
            raise ConnectorError("WebSocket target endpoint is missing")
        parsed = urlsplit(profile.endpoint)
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
        preview = self.preview(profile, message)
        payload = json.dumps(
            preview["payload"], ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        if len(payload.encode()) > MAX_REQUEST_BYTES:
            raise ConnectorError("rendered request exceeds 64 KiB")

        headers = dict(profile.headers)
        for header, env_name in profile.secret_headers.items():
            secret = os.environ.get(env_name)
            if secret is None:
                raise ConnectorError(
                    f"required secret environment variable '{env_name}' is not set"
                )
            headers[header] = secret

        raw_socket: Optional[socket.socket] = None
        try:
            raw_socket = socket.create_connection(
                (pinned_ip, port), timeout=profile.timeout_seconds
            )
            ssl_context = ssl.create_default_context() if parsed.scheme == "wss" else None
            with websocket_connect(
                profile.endpoint,
                sock=raw_socket,
                ssl=ssl_context,
                server_hostname=parsed.hostname if ssl_context else None,
                additional_headers=headers,
                compression=None,
                open_timeout=profile.timeout_seconds,
                close_timeout=min(profile.timeout_seconds, 5),
                max_size=MAX_HTTP_RESPONSE_BYTES,
            ) as connection:
                raw_socket = None  # Ownership transferred to the WebSocket connection.
                connection.send(payload)
                received = connection.recv(timeout=profile.timeout_seconds)
        except TimeoutError as exc:
            raise ConnectorError("WebSocket response timed out") from exc
        except (OSError, ValueError, WebSocketException) as exc:
            raise ConnectorError(f"WebSocket target connection failed: {exc}") from exc
        finally:
            if raw_socket is not None:
                raw_socket.close()

        if isinstance(received, bytes):
            response_bytes = received
            raw = received.decode("utf-8", errors="replace")
        else:
            raw = received
            response_bytes = raw.encode()
        if len(response_bytes) > MAX_HTTP_RESPONSE_BYTES:
            raise ConnectorError("WebSocket response exceeds 1 MiB")
        response_text, actions = _parse_observation(
            raw, profile.response_path, profile.actions_path
        )
        return TargetExchange(
            connector="websocket",
            destination=profile.endpoint,
            wire_request=preview,
            response_metadata={
                "bytes": len(response_bytes),
                "message_type": "binary" if isinstance(received, bytes) else "text",
            },
            raw_response=raw,
            response_text=response_text,
            actions=actions,
        )


class VoiceHttpConnector:
    """Bounded JSON-over-HTTP voice service with Base64 audio input and output."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        audio = message.body.get("audio_base64")
        rendered = render_request(profile, message, MAX_VOICE_RESPONSE_BYTES)
        if isinstance(audio, str) and audio:
            rendered = _redact_exact(
                rendered,
                audio,
                f"<audio omitted: {len(audio)} base64 characters>",
            )
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            headers[header] = f"<secret:{env_name}>"
        return {
            "method": profile.method,
            "url": profile.endpoint,
            "headers": headers,
            "body": rendered,
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if not profile.endpoint:
            raise ConnectorError("voice target endpoint is missing")
        audio = message.body.get("audio_base64")
        if audio is not None:
            if not isinstance(audio, str):
                raise ConnectorError("voice audio must be Base64 text")
            try:
                decoded_audio = base64.b64decode(audio, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ConnectorError("voice audio is not valid Base64") from exc
            if len(decoded_audio) > MAX_VOICE_AUDIO_BYTES:
                raise ConnectorError("voice audio exceeds 6 MiB")

        parsed = urlsplit(profile.endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
        body = render_request(profile, message, MAX_VOICE_RESPONSE_BYTES)
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            secret = os.environ.get(env_name)
            if secret is None:
                raise ConnectorError(
                    f"required secret environment variable '{env_name}' is not set"
                )
            headers[header] = secret
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection_type = (
            _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        )
        connection = connection_type(
            parsed.hostname or "", pinned_ip, port, profile.timeout_seconds
        )
        try:
            connection.request(profile.method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ConnectorError("voice target redirects are not followed")
            payload = response.read(MAX_VOICE_RESPONSE_BYTES + 1)
            if len(payload) > MAX_VOICE_RESPONSE_BYTES:
                raise ConnectorError("voice response exceeds 9 MiB")
        except ConnectorError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise ConnectorError(f"voice target connection failed: {exc}") from exc
        finally:
            connection.close()

        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ConnectorError("voice target response must be JSON") from exc
        transcript = _extract_path(decoded, profile.response_path)
        if not isinstance(transcript, str):
            raise ConnectorError("voice transcript response path did not resolve to text")

        response_audio = (
            _extract_path(decoded, profile.voice_response_audio_path)
            if profile.voice_response_audio_path
            else None
        )
        response_audio_url: Optional[str] = None
        redacted = decoded
        if response_audio is not None:
            if not isinstance(response_audio, str):
                raise ConnectorError("voice response audio path did not resolve to Base64 text")
            try:
                response_audio_bytes = base64.b64decode(response_audio, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ConnectorError("voice response audio is not valid Base64") from exc
            if len(response_audio_bytes) > MAX_VOICE_AUDIO_BYTES:
                raise ConnectorError("voice response audio exceeds 6 MiB")
            response_audio_url = (
                f"data:{profile.voice_response_audio_type};base64,{response_audio}"
            )
            redacted = _replace_path(
                decoded,
                profile.voice_response_audio_path,
                f"<audio omitted: {len(response_audio_bytes)} bytes>",
            )

        raw = json.dumps(redacted, ensure_ascii=False)
        _unused_text, actions = _parse_observation(
            raw, profile.response_path, profile.actions_path
        )
        return TargetExchange(
            connector="voice",
            destination=profile.endpoint,
            wire_request=self.preview(profile, message),
            response_metadata={
                "status": response.status,
                "reason": response.reason,
                "content_type": response.getheader("Content-Type"),
                "response_audio_data_url": response_audio_url,
            },
            raw_response=raw,
            response_text=transcript,
            actions=actions,
        )


class _CancelOnError:
    def __init__(self, connection: Any, cancel: Any) -> None:
        self.connection = connection
        self.cancel = cancel

    def __enter__(self) -> Any:
        return self.connection

    def __exit__(self, exc_type: Any, _exc: Any, _traceback: Any) -> None:
        if exc_type is not None:
            self.cancel(self.connection)
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()


class OpticalHttpConnector:
    """Bounded image delivery to a QR, OCR, or multimodal agent service."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        image = message.body.get("image_base64")
        rendered = render_request(profile, message, 12 * 1024 * 1024)
        if isinstance(image, str) and image:
            rendered = _redact_exact(
                rendered,
                image,
                f"<image omitted: {len(image)} base64 characters>",
            )
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            headers[header] = f"<secret:{env_name}>"
        return {
            "method": profile.method,
            "url": profile.endpoint,
            "headers": headers,
            "body": rendered,
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if not profile.endpoint:
            raise ConnectorError("optical target endpoint is missing")
        image = message.body.get("image_base64")
        if not isinstance(image, str) or not image:
            raise ConnectorError("optical targets require an image attachment")
        try:
            decoded_image = base64.b64decode(image, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ConnectorError("optical image is not valid Base64") from exc
        if len(decoded_image) > 8 * 1024 * 1024:
            raise ConnectorError("optical image exceeds 8 MiB")

        parsed = urlsplit(profile.endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
        body = render_request(profile, message, 12 * 1024 * 1024)
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            secret = os.environ.get(env_name)
            if secret is None:
                raise ConnectorError(
                    f"required secret environment variable '{env_name}' is not set"
                )
            headers[header] = secret
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection_type = (
            _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        )
        connection = connection_type(
            parsed.hostname or "", pinned_ip, port, profile.timeout_seconds
        )
        try:
            connection.request(profile.method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ConnectorError("optical target redirects are not followed")
            payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(payload) > MAX_HTTP_RESPONSE_BYTES:
                raise ConnectorError("optical response exceeds 1 MiB")
        except ConnectorError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise ConnectorError(f"optical target connection failed: {exc}") from exc
        finally:
            connection.close()

        raw = payload.decode("utf-8", errors="replace")
        response_text, actions = _parse_observation(
            raw, profile.response_path, profile.actions_path
        )
        return TargetExchange(
            connector="optical",
            destination=profile.endpoint,
            wire_request=self.preview(profile, message),
            response_metadata={
                "status": response.status,
                "reason": response.reason,
                "content_type": response.getheader("Content-Type"),
                "input_image_bytes": len(decoded_image),
            },
            raw_response=raw,
            response_text=response_text,
            actions=actions,
        )


class VoiceStreamConnector:
    """Bounded WebSocket media stream for voice services and SIP media gateways."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        audio = self._audio_bytes(message)
        start_event = render_template(
            profile.request_template,
            message,
            max_bytes=MAX_REQUEST_BYTES,
        )
        return {
            "url": profile.endpoint,
            "headers": self._headers(profile, redact=True),
            "start_event": start_event,
            "audio": {
                "bytes": len(audio),
                "chunk_bytes": profile.voice_stream_chunk_bytes,
                "chunks": (
                    (len(audio) + profile.voice_stream_chunk_bytes - 1)
                    // profile.voice_stream_chunk_bytes
                    if audio
                    else 0
                ),
                "mime_type": message.body.get("audio_mime_type"),
            },
            "chunk_event": "<configured template; audio redacted>",
            "end_event": json.loads(profile.voice_stream_end_template),
            "limits": {
                "max_events": profile.voice_stream_max_events,
                "timeout_seconds": profile.timeout_seconds,
            },
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if websocket_connect is None:
            raise ConnectorError("streaming voice connector requires websockets")
        if not profile.endpoint:
            raise ConnectorError("streaming voice endpoint is missing")
        audio = self._audio_bytes(message)
        parsed = urlsplit(profile.endpoint)
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
        headers = self._headers(profile, redact=False)
        start_event = render_template(
            profile.request_template, message, max_bytes=MAX_REQUEST_BYTES
        )
        end_event = render_template(
            profile.voice_stream_end_template,
            message,
            max_bytes=MAX_REQUEST_BYTES,
        )

        transcripts: List[str] = []
        audio_parts: List[bytes] = []
        audio_response_bytes = 0
        actions: List[ObservedAction] = []
        raw_events: List[Any] = []
        raw_size = 2
        event_count = 0
        done = False
        raw_socket: Optional[socket.socket] = None
        connection: Any = None
        started = time.monotonic()
        try:
            raw_socket = socket.create_connection(
                (pinned_ip, port), timeout=profile.timeout_seconds
            )
            ssl_context = ssl.create_default_context() if parsed.scheme == "wss" else None
            with _CancelOnError(
                websocket_connect(
                    profile.endpoint,
                    sock=raw_socket,
                    ssl=ssl_context,
                    server_hostname=parsed.hostname if ssl_context else None,
                    additional_headers=headers,
                    compression=None,
                    open_timeout=profile.timeout_seconds,
                    close_timeout=min(profile.timeout_seconds, 5),
                    max_size=MAX_HTTP_RESPONSE_BYTES,
                ),
                lambda active: self._cancel(active, profile, message),
            ) as connection:
                raw_socket = None
                connection.send(json.dumps(start_event, ensure_ascii=False))
                for offset in range(0, len(audio), profile.voice_stream_chunk_bytes):
                    chunk = base64.b64encode(
                        audio[offset : offset + profile.voice_stream_chunk_bytes]
                    ).decode()
                    chunk_event = render_template(
                        profile.voice_stream_chunk_template,
                        message,
                        max_bytes=MAX_REQUEST_BYTES,
                        extras={"{{audio_chunk_base64}}": chunk},
                    )
                    connection.send(json.dumps(chunk_event, ensure_ascii=False))
                connection.send(json.dumps(end_event, ensure_ascii=False))

                while event_count < profile.voice_stream_max_events:
                    remaining = profile.timeout_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        raise ConnectorError("streaming voice response timed out")
                    received = connection.recv(timeout=remaining)
                    event_count += 1
                    if isinstance(received, bytes):
                        received = received.decode("utf-8", errors="replace")
                    try:
                        event = json.loads(received)
                    except json.JSONDecodeError as exc:
                        raise ConnectorError(
                            "streaming voice response event must be JSON"
                        ) from exc
                    if not isinstance(event, dict):
                        raise ConnectorError(
                            "streaming voice response event must be an object"
                        )

                    transcript = _extract_path(event, profile.response_path)
                    if isinstance(transcript, str):
                        transcripts.append(transcript)
                    audio_value = (
                        _extract_path(event, profile.voice_response_audio_path)
                        if profile.voice_response_audio_path
                        else None
                    )
                    redacted_event = event
                    if audio_value is not None:
                        if not isinstance(audio_value, str):
                            raise ConnectorError(
                                "streaming voice audio path did not resolve to Base64 text"
                            )
                        try:
                            audio_chunk = base64.b64decode(audio_value, validate=True)
                        except (ValueError, binascii.Error) as exc:
                            raise ConnectorError(
                                "streaming voice response audio is not valid Base64"
                            ) from exc
                        if audio_response_bytes + len(audio_chunk) > MAX_VOICE_AUDIO_BYTES:
                            raise ConnectorError("streaming voice response audio exceeds 6 MiB")
                        audio_parts.append(audio_chunk)
                        audio_response_bytes += len(audio_chunk)
                        redacted_event = _replace_path(
                            event,
                            profile.voice_response_audio_path,
                            f"<audio chunk omitted: {len(audio_chunk)} bytes>",
                        )
                    action_values = (
                        _extract_path(event, profile.actions_path)
                        if profile.actions_path
                        else None
                    )
                    if isinstance(action_values, list):
                        for item in action_values:
                            if len(actions) >= 100 or not isinstance(item, dict):
                                break
                            name = item.get("name") or item.get("tool")
                            arguments = item.get("arguments") or item.get("args") or {}
                            if isinstance(name, str) and isinstance(arguments, dict):
                                actions.append(
                                    ObservedAction(name=name[:256], arguments=arguments)
                                )
                    event_size = len(json.dumps(redacted_event, ensure_ascii=False).encode())
                    if raw_size + event_size <= MAX_HTTP_RESPONSE_BYTES:
                        raw_events.append(redacted_event)
                        raw_size += event_size
                    if (
                        str(_extract_path(event, profile.voice_stream_done_path))
                        == profile.voice_stream_done_value
                    ):
                        done = True
                        break
                if not done:
                    raise ConnectorError("streaming voice event limit reached before completion")
        except ConnectorError:
            raise
        except TimeoutError as exc:
            raise ConnectorError("streaming voice response timed out") from exc
        except (OSError, ValueError, WebSocketException) as exc:
            raise ConnectorError(f"streaming voice connection failed: {exc}") from exc
        finally:
            if raw_socket is not None:
                raw_socket.close()

        response_audio = b"".join(audio_parts)
        audio_url = (
            f"data:{profile.voice_response_audio_type};base64,"
            f"{base64.b64encode(response_audio).decode()}"
            if response_audio
            else None
        )
        response_text = "".join(transcripts)
        return TargetExchange(
            connector="voice-stream",
            destination=profile.endpoint,
            wire_request=self.preview(profile, message),
            response_metadata={
                "events": event_count,
                "audio_chunks": len(audio_parts),
                "response_audio_data_url": audio_url,
                "completed": done,
            },
            raw_response=json.dumps(raw_events, ensure_ascii=False),
            response_text=response_text,
            actions=actions,
        )

    @staticmethod
    def _audio_bytes(message: Message) -> bytes:
        audio = message.body.get("audio_base64")
        if audio is None or audio == "":
            return b""
        if not isinstance(audio, str):
            raise ConnectorError("streaming voice audio must be Base64 text")
        try:
            decoded = base64.b64decode(audio, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ConnectorError("streaming voice audio is not valid Base64") from exc
        if len(decoded) > MAX_VOICE_AUDIO_BYTES:
            raise ConnectorError("streaming voice audio exceeds 6 MiB")
        return decoded

    @staticmethod
    def _headers(profile: TargetProfile, *, redact: bool) -> Dict[str, str]:
        headers = dict(profile.headers)
        for header, env_name in profile.secret_headers.items():
            if redact:
                headers[header] = f"<secret:{env_name}>"
                continue
            secret = os.environ.get(env_name)
            if secret is None:
                raise ConnectorError(
                    f"required secret environment variable '{env_name}' is not set"
                )
            headers[header] = secret
        return headers

    @staticmethod
    def _cancel(connection: Any, profile: TargetProfile, message: Message) -> None:
        if connection is None:
            return
        try:
            event = render_template(
                profile.voice_stream_cancel_template,
                message,
                max_bytes=MAX_REQUEST_BYTES,
            )
            connection.send(json.dumps(event, ensure_ascii=False))
        except Exception:
            pass


class DeviceBridgeConnector:
    """Short-lived physical stimulus with optional out-of-band observation."""

    def preview(self, profile: TargetProfile, message: Message) -> Dict[str, Any]:
        extras = self._extras(profile)
        headers = self._headers(profile, redact=True)
        return {
            "action": {
                "method": profile.method,
                "url": profile.endpoint,
                "headers": headers,
                "body": render_template(
                    profile.request_template,
                    message,
                    max_bytes=MAX_REQUEST_BYTES,
                    extras=extras,
                ),
            },
            "mandatory_stop": {
                "method": "POST",
                "url": profile.hardware_stop_endpoint,
                "headers": headers,
                "body": render_template(
                    profile.hardware_stop_template,
                    message,
                    max_bytes=MAX_REQUEST_BYTES,
                    extras=extras,
                ),
            },
            "guardrails": {
                "kind": profile.hardware_kind,
                "device_id": profile.hardware_device_id,
                "resource": profile.hardware_resource,
                "duration_ms": profile.hardware_duration_ms,
                "concurrency": 1,
            },
            "observer": {
                "kind": profile.observer_kind,
                "url": profile.observer_url,
                "selector": profile.observer_selector,
                "wait_ms": profile.observer_wait_ms,
                "capture_screenshot": profile.observer_capture_screenshot,
            },
        }

    def execute(self, profile: TargetProfile, message: Message) -> TargetExchange:
        if not profile.endpoint or not profile.hardware_stop_endpoint:
            raise ConnectorError("device bridge endpoints are missing")
        extras = self._extras(profile)
        headers = self._headers(profile, redact=False)
        action_body = render_template(
            profile.request_template,
            message,
            max_bytes=MAX_REQUEST_BYTES,
            extras=extras,
        )
        stop_body = render_template(
            profile.hardware_stop_template,
            message,
            max_bytes=MAX_REQUEST_BYTES,
            extras=extras,
        )
        action_result: Optional[Dict[str, Any]] = None
        action_error: Optional[ConnectorError] = None
        before_observation = None
        after_observation = None
        if profile.observer_kind != "none":
            from .observers import capture_observation

            before_observation = capture_observation(profile, "before")
        try:
            action_result = self._post(
                profile.endpoint,
                profile.method,
                headers,
                action_body,
                profile.timeout_seconds,
            )
        except ConnectorError as exc:
            action_error = exc

        if action_error is None and profile.observer_kind != "none":
            try:
                time.sleep(profile.observer_wait_ms / 1_000)
                after_observation = capture_observation(profile, "after")
            except ConnectorError as exc:
                action_error = ConnectorError(f"out-of-band observation failed: {exc}")

        try:
            stop_result = self._post(
                profile.hardware_stop_endpoint,
                "POST",
                headers,
                stop_body,
                min(profile.timeout_seconds, 10),
            )
            if not 200 <= int(stop_result["status"]) < 300:
                raise ConnectorError(
                    f"bridge returned stop status {stop_result['status']}"
                )
        except ConnectorError as exc:
            detail = f"device bridge emergency stop failed: {exc}"
            if action_error is not None:
                detail += f"; action also failed: {action_error}"
            raise ConnectorError(detail) from exc
        if action_error is not None:
            raise action_error
        if action_result is None:  # Defense in depth for type narrowing.
            raise ConnectorError("device bridge returned no action result")

        action_raw = str(action_result["raw"])
        if after_observation is None:
            raw = action_raw
            response_text, actions = _parse_observation(
                raw, profile.response_path, profile.actions_path
            )
            observation_metadata = None
        else:
            response_text, actions = _parse_observation(
                after_observation.raw, profile.response_path, profile.actions_path
            )
            if not profile.response_path:
                response_text = after_observation.text
            observation_metadata = {
                "before": before_observation.to_dict() if before_observation else None,
                "after": after_observation.to_dict(),
            }
            raw = json.dumps(
                {
                    "bridge_response": _json_or_text(action_raw),
                    "observation": _observation_without_media(
                        observation_metadata
                    ),
                },
                ensure_ascii=False,
            )
        return TargetExchange(
            connector="device-bridge",
            destination=profile.endpoint,
            wire_request=self.preview(profile, message),
            response_metadata={
                "status": action_result["status"],
                "reason": action_result["reason"],
                "content_type": action_result["content_type"],
                "stop_status": stop_result["status"],
                "stop_confirmed": True,
                "device_id": profile.hardware_device_id,
                "resource": profile.hardware_resource,
                "duration_ms": profile.hardware_duration_ms,
                "observation": observation_metadata,
            },
            raw_response=raw,
            response_text=response_text,
            actions=actions,
        )

    @staticmethod
    def _extras(profile: TargetProfile) -> Dict[str, Any]:
        return {
            "{{device_id}}": profile.hardware_device_id or "",
            "{{operation}}": profile.hardware_operation,
            "{{resource}}": profile.hardware_resource or "",
            "{{duration_ms}}": profile.hardware_duration_ms,
        }

    @staticmethod
    def _headers(profile: TargetProfile, *, redact: bool) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", **profile.headers}
        for header, env_name in profile.secret_headers.items():
            if redact:
                headers[header] = f"<secret:{env_name}>"
                continue
            secret = os.environ.get(env_name)
            if secret is None:
                raise ConnectorError(
                    f"required secret environment variable '{env_name}' is not set"
                )
            headers[header] = secret
        return headers

    @staticmethod
    def _post(
        endpoint: str,
        method: str,
        headers: Dict[str, str],
        body: Any,
        timeout: float,
    ) -> Dict[str, Any]:
        parsed = urlsplit(endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        connection_type = (
            _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        )
        connection = connection_type(parsed.hostname or "", pinned_ip, port, timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        try:
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ConnectorError("device bridge redirects are not followed")
            payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(payload) > MAX_HTTP_RESPONSE_BYTES:
                raise ConnectorError("device bridge response exceeds 1 MiB")
            return {
                "status": response.status,
                "reason": response.reason,
                "content_type": response.getheader("Content-Type"),
                "raw": payload.decode("utf-8", errors="replace"),
            }
        except ConnectorError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise ConnectorError(f"device bridge connection failed: {exc}") from exc
        finally:
            connection.close()


CONNECTORS: Dict[str, Connector] = {
    "http": HttpConnector(),
    "tcp": TcpConnector(),
    "mqtt": MqttConnector(),
    "websocket": WebSocketConnector(),
    "voice": VoiceHttpConnector(),
    "voice-stream": VoiceStreamConnector(),
    "optical": OpticalHttpConnector(),
    "device-bridge": DeviceBridgeConnector(),
}


def connector_for(profile: TargetProfile) -> Connector:
    try:
        return CONNECTORS[profile.connector]
    except KeyError:
        raise ConnectorError(f"unsupported target connector: {profile.connector}") from None
