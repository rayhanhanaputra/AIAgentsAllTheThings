from fastapi.testclient import TestClient
import pytest
import base64
from io import BytesIO
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
import socketserver
import threading

import harness.api.connectors as connectors
from harness.api.app import create_app
from PIL import Image


class _AgentHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path == "/v1/chat/completions":
            canonical = json.loads(request["messages"][-1]["content"])
            if "raw_response" in canonical:
                raw = json.loads(canonical["raw_response"])
                mapped = {
                    "response_text": f"normalized: {raw['answer']}",
                    "actions": raw["actions"],
                    "events": [
                        {
                            "event_type": "target.tool_observed",
                            "data": {"count": len(raw["actions"])},
                        }
                    ],
                    "metadata": {"format": "test-normalized"},
                }
                response = json.dumps(
                    {"choices": [{"message": {"content": json.dumps(mapped)}}]}
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            mapped = {
                "command": "inspect_input",
                "parameters": {"topic": canonical["topic"]},
            }
            response = json.dumps(
                {"choices": [{"message": {"content": json.dumps(mapped)}}]}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return
        response = json.dumps(
            {
                "answer": f"captured: {request.get('input', '')} LEAK-MARKER",
                "actions": [{"name": "open_valve", "arguments": {"zone": 1}}],
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, _format, *_args):
        return


@contextmanager
def local_agent_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/agent"
    finally:
        server.shutdown()
        thread.join()


class _TcpAgentHandler(socketserver.StreamRequestHandler):
    def handle(self):
        request = json.loads(self.rfile.readline())
        response = {
            "answer": f"tcp captured: {request.get('input', '')} TCP-MARKER",
            "actions": [{"name": "unlock_gate", "arguments": {}}],
        }
        self.wfile.write((json.dumps(response) + "\n").encode())


@contextmanager
def local_tcp_agent_server():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _TcpAgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _create_http_target(client: TestClient) -> dict:
    response = client.post(
        "/api/targets",
        json={
            "name": "Test target",
            "environment": "staging",
            "connector": "http",
            "endpoint": "http://127.0.0.1:8080/agent",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_new_workspace_has_no_implicit_simulator(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))

    response = client.get("/api/targets")
    assert response.status_code == 200
    assert response.json() == {"targets": []}


def test_legacy_simulator_profile_is_removed_during_store_migration(tmp_path):
    database = tmp_path / "runs.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE target_profiles (
                id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO target_profiles VALUES (?, ?, ?, ?)",
            (
                "legacy-simulator",
                json.dumps(
                    {
                        "id": "legacy-simulator",
                        "name": "Local Simulator",
                        "environment": "simulation",
                        "connector": "simulator",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    client = TestClient(create_app(database))

    assert client.get("/api/targets").json() == {"targets": []}


def test_legacy_simulation_environment_becomes_staging(tmp_path):
    database = tmp_path / "runs.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE target_profiles (
                id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        profile = {
            "id": "legacy-http",
            "name": "Legacy lab target",
            "environment": "simulation",
            "connector": "http",
            "endpoint": "http://127.0.0.1:8080/agent",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        connection.execute(
            "INSERT INTO target_profiles VALUES (?, ?, ?, ?)",
            (
                profile["id"],
                json.dumps(profile),
                profile["created_at"],
                profile["updated_at"],
            ),
        )

    client = TestClient(create_app(database))

    targets = client.get("/api/targets").json()["targets"]
    assert len(targets) == 1
    assert targets[0]["environment"] == "staging"


@pytest.mark.parametrize(
    ("adapter", "fields", "expected_key"),
    [
        ("prompt-text", {"prompt": "hello"}, "prompt"),
        ("json-field", {"note": "hello"}, "note"),
        ("sensor-value", {"level": 42, "note": "hello"}, "level"),
        ("reading-stream", {"window": [1, 0, 1]}, "window"),
        ("binary-toggle", {"bits": "1010"}, "bits"),
        ("morse-blink", {"signal": "SOS"}, "morse"),
        ("voice-transcript", {"spoken": "hello", "dtmf": "1"}, "transcript"),
        ("qr-code", {"text": "hello"}, "scanned_text"),
        ("text-in-image", {"text": "hello"}, "scanned_text"),
        ("agent-note", {"text": "hello"}, "context"),
        ("retrieved-doc", {"text": "hello"}, "context"),
        ("ble-advert", {"text": "hello"}, "advertised"),
        ("nfc-tag", {"text": "hello"}, "advertised"),
    ],
)
def test_channel_adapters_are_available_in_workbench(
    tmp_path, adapter, fields, expected_key
):
    client = TestClient(create_app(tmp_path / "runs.db"))
    target = _create_http_target(client)

    response = client.post(
        f"/api/targets/{target['id']}/preview",
        json={"adapter": adapter, "fields": fields},
    )

    assert response.status_code == 200
    body = response.json()
    assert expected_key in body["message"]["body"]


def test_channel_run_rejects_unknown_adapter_and_empty_fields(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    target = _create_http_target(client)

    unknown = client.post(
        f"/api/targets/{target['id']}/preview",
        json={"adapter": "shell", "fields": {"command": "whoami"}},
    )
    empty = client.post(
        f"/api/targets/{target['id']}/preview",
        json={"adapter": "prompt-text", "fields": {}},
    )

    assert unknown.status_code == 422
    assert empty.status_code == 422


def test_target_profile_preview_redacts_secret_references(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    created = client.post(
        "/api/targets",
        json={
            "name": "Staging agent",
            "environment": "staging",
            "connector": "http",
            "endpoint": "http://127.0.0.1:8080/agent",
            "secret_headers": {"Authorization": "TEST_AGENT_TOKEN"},
        },
    )
    assert created.status_code == 201
    target = created.json()
    assert "secret" not in json.dumps(target).lower().replace("secret_headers", "")

    preview = client.post(
        f"/api/targets/{target['id']}/preview",
        json={"adapter": "prompt-text", "fields": {"prompt": "hello"}},
    )
    assert preview.status_code == 200
    assert preview.json()["wire_request"]["headers"]["Authorization"] == (
        "<secret:TEST_AGENT_TOKEN>"
    )

    plaintext_secret = client.post(
        "/api/targets",
        json={
            "name": "Unsafe target",
            "environment": "staging",
            "connector": "http",
            "endpoint": "http://127.0.0.1:8080/agent",
            "headers": {"Authorization": "Bearer plaintext"},
        },
    )
    assert plaintext_secret.status_code == 422


def test_production_target_requires_acknowledgement_and_evaluates_evidence(tmp_path):
    with local_agent_server() as endpoint:
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "Production farm agent",
                "environment": "production",
                "connector": "http",
                "endpoint": endpoint,
                "response_path": "answer",
                "actions_path": "actions",
                "evidence": {
                    "response_markers": ["LEAK-MARKER"],
                    "forbidden_tools": ["open_valve"],
                },
            },
        ).json()
        request = {
            "target_id": target["id"],
            "adapter": "prompt-text",
            "fields": {"prompt": "authorized test"},
        }

        blocked = client.post("/api/workbench/runs", json=request)
        assert blocked.status_code == 409

        request["production_acknowledged"] = True
        executed = client.post("/api/workbench/runs", json=request)
        assert executed.status_code == 200
        result = executed.json()
        assert result["analysis"]["verdict"] == "confirmed_violation"
        assert result["metadata"]["target"]["environment"] == "production"
        assert result["metadata"]["exchange"]["actions"][0]["name"] == "open_valve"


def test_input_mapper_converts_canonical_channel_before_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MAPPER_KEY", "dummy-key")
    with local_agent_server() as endpoint:
        client = TestClient(create_app(tmp_path / "runs.db"))
        origin = endpoint.rsplit("/", 1)[0]
        target = client.post(
            "/api/targets",
            json={
                "name": "Mapped staging agent",
                "environment": "staging",
                "connector": "http",
                "endpoint": endpoint,
                "request_template": '"{{mapped}}"',
                "response_path": "answer",
                "mapper_enabled": True,
                "mapper_endpoint": f"{origin}/v1/chat/completions",
                "mapper_model": "dummy-mapper",
                "mapper_api_key_env": "TEST_MAPPER_KEY",
                "mapper_instructions": "Return command and parameters.",
                "mapper_required_keys": ["command", "parameters"],
            },
        )
        assert target.status_code == 201
        result = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target.json()["id"],
                "adapter": "sensor-value",
                "fields": {"level": 42, "note": "map this"},
            },
        )
        assert result.status_code == 200
        body = result.json()
        assert body["metadata"]["mapper"]["mapped_request"]["command"] == "inspect_input"
        assert body["metadata"]["exchange"]["wire_request"]["body"]["command"] == "inspect_input"
        assert any(event["event_type"] == "input.mapped" for event in body["events"])


def test_input_mapper_requires_placeholder_and_env_reference(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    response = client.post(
        "/api/targets",
        json={
            "name": "Unsafe mapper",
            "environment": "staging",
            "connector": "http",
            "endpoint": "http://127.0.0.1:9101/agent",
            "mapper_enabled": True,
            "mapper_endpoint": "http://127.0.0.1:9101/v1/chat/completions",
            "mapper_model": "dummy",
            "mapper_api_key_env": "plaintext-secret",
            "mapper_instructions": "Return JSON.",
        },
    )
    assert response.status_code == 422


def test_response_mapper_normalizes_captured_response_and_preserves_raw(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TEST_RESPONSE_MAPPER_KEY", "dummy-key")
    with local_agent_server() as endpoint:
        client = TestClient(create_app(tmp_path / "runs.db"))
        origin = endpoint.rsplit("/", 1)[0]
        target = client.post(
            "/api/targets",
            json={
                "name": "Mapped response target",
                "environment": "staging",
                "connector": "http",
                "endpoint": endpoint,
                "request_template": '{"input":"{{input}}"}',
                "actions_path": "actions",
                "response_mapper_enabled": True,
                "response_mapper_endpoint": f"{origin}/v1/chat/completions",
                "response_mapper_model": "dummy-response-mapper",
                "response_mapper_api_key_env": "TEST_RESPONSE_MAPPER_KEY",
                "response_mapper_instructions": "Preserve observed actions.",
                "evidence": {"forbidden_tools": ["open_valve"]},
            },
        )
        assert target.status_code == 201

        result = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target.json()["id"],
                "adapter": "prompt-text",
                "fields": {"prompt": "inspect this"},
            },
        )

    assert result.status_code == 200
    body = result.json()
    assert body["response_text"].startswith("normalized: captured:")
    assert "LEAK-MARKER" in body["metadata"]["exchange"]["raw_response"]
    assert body["metadata"]["exchange"]["actions"][0]["name"] == "open_valve"
    assert body["metadata"]["response_mapper"]["status"] == "completed"
    assert body["metadata"]["response_mapper"][
        "used_for_deterministic_evidence"
    ] is False
    assert body["metadata"]["response_mapper"]["normalized_metadata"] == {
        "format": "test-normalized"
    }
    assert body["analysis"]["verdict"] == "confirmed_violation"
    assert any(
        event["event_type"] == "target.tool_observed" for event in body["events"]
    )


def test_response_mapper_failure_falls_back_to_deterministic_extraction(tmp_path):
    with local_agent_server() as endpoint:
        client = TestClient(create_app(tmp_path / "runs.db"))
        origin = endpoint.rsplit("/", 1)[0]
        target = client.post(
            "/api/targets",
            json={
                "name": "Unavailable response mapper",
                "environment": "staging",
                "connector": "http",
                "endpoint": endpoint,
                "request_template": '{"input":"{{input}}"}',
                "response_path": "answer",
                "response_mapper_enabled": True,
                "response_mapper_endpoint": f"{origin}/v1/chat/completions",
                "response_mapper_model": "dummy-response-mapper",
                "response_mapper_api_key_env": "MISSING_RESPONSE_MAPPER_KEY",
            },
        )
        assert target.status_code == 201
        result = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target.json()["id"],
                "adapter": "prompt-text",
                "fields": {"prompt": "fallback please"},
            },
        )

    assert result.status_code == 200
    body = result.json()
    assert body["response_text"].startswith("captured:")
    assert body["metadata"]["response_mapper"]["status"] == "failed"
    assert body["metadata"]["response_mapper"]["fallback"] == (
        "deterministic extraction"
    )
    assert any(
        event["event_type"] == "response.normalization_failed"
        for event in body["events"]
    )


def test_production_campaign_forces_single_concurrency(tmp_path):
    with local_agent_server() as endpoint:
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "Production batch target",
                "environment": "production",
                "connector": "http",
                "endpoint": endpoint,
            },
        ).json()
        response = client.post(
            "/api/campaigns/runs",
            json={
                "target_id": target["id"],
                "adapter": "prompt-text",
                "fields_template": {"prompt": "{{position}}"},
                "payloads": ["one", "two"],
                "concurrency": 4,
                "production_acknowledged": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["effective_concurrency"] == 1


def test_tcp_target_executes_on_private_network_and_extracts_actions(tmp_path):
    with local_tcp_agent_server() as port:
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "TCP staging agent",
                "environment": "staging",
                "connector": "tcp",
                "host": "127.0.0.1",
                "port": port,
                "response_path": "answer",
                "actions_path": "actions",
                "evidence": {
                    "response_markers": ["TCP-MARKER"],
                    "forbidden_tools": ["unlock_gate"],
                },
            },
        ).json()
        response = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target["id"],
                "adapter": "prompt-text",
                "fields": {"prompt": "authorized tcp test"},
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["analysis"]["verdict"] == "confirmed_violation"
        assert result["metadata"]["exchange"]["actions"][0]["name"] == "unlock_gate"


def test_link_local_target_is_rejected_before_connection(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    target = client.post(
        "/api/targets",
        json={
            "name": "Metadata endpoint",
            "environment": "production",
            "connector": "http",
            "endpoint": "https://169.254.169.254/latest/meta-data",
        },
    ).json()
    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": target["id"],
            "adapter": "prompt-text",
            "fields": {"prompt": "test"},
            "production_acknowledged": True,
        },
    )
    assert response.status_code == 502
    assert "prohibited" in response.json()["detail"]


def test_mqtt_target_publishes_and_captures_correlated_response(tmp_path, monkeypatch):
    published = {}

    class FakePublication:
        rc = connectors.mqtt.MQTT_ERR_SUCCESS

        def wait_for_publish(self, timeout):
            published["publish_timeout"] = timeout

        def is_published(self):
            return True

    class FakeClient:
        def __init__(self, *_args, **kwargs):
            published["client_id"] = kwargs["client_id"]
            self.on_connect = None
            self.on_subscribe = None
            self.on_message = None

        def username_pw_set(self, username, password):
            published["credentials"] = (username, password)

        def connect(self, host, port, keepalive):
            published["connection"] = (host, port, keepalive)
            return connectors.mqtt.MQTT_ERR_SUCCESS

        def loop_start(self):
            self.on_connect(self, None, None, 0, None)

        def subscribe(self, topic, qos):
            published["subscription"] = (topic, qos)
            self.on_subscribe(self, None, 1, [0], None)
            return connectors.mqtt.MQTT_ERR_SUCCESS, 1

        def publish(self, topic, payload, qos, retain):
            published["request"] = (topic, json.loads(payload), qos, retain)
            response = type(
                "Message",
                (),
                {
                    "payload": json.dumps(
                        {
                            "answer": "MQTT-MARKER",
                            "actions": [{"name": "open_valve", "arguments": {}}],
                        }
                    ).encode()
                },
            )()
            self.on_message(self, None, response)
            return FakePublication()

        def disconnect(self):
            return None

        def loop_stop(self):
            return None

    monkeypatch.setattr(connectors.mqtt, "Client", FakeClient)
    monkeypatch.setattr(connectors, "_resolve_destination", lambda *_args, **_kwargs: "127.0.0.1")
    monkeypatch.setenv("TEST_MQTT_USER", "workbench")
    monkeypatch.setenv("TEST_MQTT_PASSWORD", "not-returned-to-browser")

    client = TestClient(create_app(tmp_path / "runs.db"))
    target = client.post(
        "/api/targets",
        json={
            "name": "Smart farm MQTT agent",
            "environment": "staging",
            "connector": "mqtt",
            "host": "broker.internal",
            "port": 1883,
            "mqtt_publish_topic": "farm/agent/requests",
            "mqtt_response_topic": "farm/agent/responses/{{message_id}}",
            "mqtt_qos": 1,
            "mqtt_username_env": "TEST_MQTT_USER",
            "mqtt_password_env": "TEST_MQTT_PASSWORD",
            "request_template": '{"id":"{{message_id}}","input":"{{input}}"}',
            "response_path": "answer",
            "actions_path": "actions",
            "evidence": {
                "response_markers": ["MQTT-MARKER"],
                "forbidden_tools": ["open_valve"],
            },
        },
    ).json()

    preview = client.post(
        f"/api/targets/{target['id']}/preview",
        json={"adapter": "sensor-value", "fields": {"level": 1, "note": "test"}},
    )
    assert preview.status_code == 200
    assert preview.json()["wire_request"]["username"] == "<secret:TEST_MQTT_USER>"
    assert "not-returned-to-browser" not in preview.text

    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": target["id"],
            "adapter": "sensor-value",
            "fields": {"level": 1, "note": "authorized test"},
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["analysis"]["verdict"] == "confirmed_violation"
    assert result["metadata"]["exchange"]["actions"][0]["name"] == "open_valve"
    assert published["credentials"] == ("workbench", "not-returned-to-browser")
    assert published["request"][0] == "farm/agent/requests"
    assert published["subscription"][0].startswith("farm/agent/responses/")
    assert "{{message_id}}" not in published["subscription"][0]


def test_mqtt_target_rejects_wildcard_topics(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    response = client.post(
        "/api/targets",
        json={
            "name": "Unsafe MQTT target",
            "environment": "staging",
            "connector": "mqtt",
            "host": "127.0.0.1",
            "port": 1883,
            "mqtt_publish_topic": "farm/#",
            "mqtt_response_topic": "farm/responses/+",
        },
    )
    assert response.status_code == 422


def test_websocket_target_sends_one_message_and_captures_response(tmp_path, monkeypatch):
    exchange = {}

    class FakeSocket:
        def close(self):
            exchange["socket_closed"] = True

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            exchange["connection_closed"] = True

        def send(self, payload):
            exchange["payload"] = json.loads(payload)

        def recv(self, timeout):
            exchange["receive_timeout"] = timeout
            return json.dumps(
                {
                    "answer": "WS-MARKER",
                    "actions": [{"name": "unlock_gate", "arguments": {}}],
                }
            )

    def fake_connect(uri, **kwargs):
        exchange["uri"] = uri
        exchange["headers"] = kwargs["additional_headers"]
        exchange["max_size"] = kwargs["max_size"]
        return FakeConnection()

    monkeypatch.setattr(connectors, "_resolve_destination", lambda *_args, **_kwargs: "127.0.0.1")
    monkeypatch.setattr(connectors.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket())
    monkeypatch.setattr(connectors, "websocket_connect", fake_connect)
    monkeypatch.setenv("TEST_WS_AUTH", "Bearer server-only")

    client = TestClient(create_app(tmp_path / "runs.db"))
    target = client.post(
        "/api/targets",
        json={
            "name": "WebSocket staging agent",
            "environment": "staging",
            "connector": "websocket",
            "endpoint": "ws://127.0.0.1:8765/agent",
            "secret_headers": {"Authorization": "TEST_WS_AUTH"},
            "response_path": "answer",
            "actions_path": "actions",
            "evidence": {
                "response_markers": ["WS-MARKER"],
                "forbidden_tools": ["unlock_gate"],
            },
        },
    ).json()

    preview = client.post(
        f"/api/targets/{target['id']}/preview",
        json={"adapter": "prompt-text", "fields": {"prompt": "hello"}},
    )
    assert preview.status_code == 200
    assert preview.json()["wire_request"]["headers"]["Authorization"] == (
        "<secret:TEST_WS_AUTH>"
    )

    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": target["id"],
            "adapter": "prompt-text",
            "fields": {"prompt": "authorized websocket test"},
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["analysis"]["verdict"] == "confirmed_violation"
    assert result["metadata"]["exchange"]["actions"][0]["name"] == "unlock_gate"
    assert exchange["headers"]["Authorization"] == "Bearer server-only"
    assert exchange["payload"]["input"] == "authorized websocket test"
    assert exchange["max_size"] == connectors.MAX_HTTP_RESPONSE_BYTES


def test_public_plaintext_websocket_target_is_rejected(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    response = client.post(
        "/api/targets",
        json={
            "name": "Unsafe public socket",
            "environment": "staging",
            "connector": "websocket",
            "endpoint": "ws://agent.example.com/socket",
        },
    )
    assert response.status_code == 422


def test_voice_target_sends_audio_and_captures_playable_response(tmp_path):
    requests = []
    response_audio = base64.b64encode(b"RIFF-test-response").decode()

    class VoiceHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            requests.append(json.loads(self.rfile.read(length)))
            body = json.dumps(
                {
                    "transcript": "VOICE-MARKER",
                    "audio_base64": response_audio,
                    "actions": [{"name": "disclose_record", "arguments": {}}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), VoiceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "Voice staging agent",
                "environment": "staging",
                "connector": "voice",
                "endpoint": f"http://127.0.0.1:{server.server_port}/interact",
                "request_template": (
                    '{"transcript":"{{input}}","audio":'
                    '{"data":"{{audio_base64}}","type":"{{audio_mime_type}}"}}'
                ),
                "response_path": "transcript",
                "actions_path": "actions",
                "voice_response_audio_path": "audio_base64",
                "voice_response_audio_type": "audio/wav",
                "evidence": {
                    "response_markers": ["VOICE-MARKER"],
                    "forbidden_tools": ["disclose_record"],
                },
            },
        ).json()
        request_audio = base64.b64encode(b"RIFF-private-request-audio").decode()
        fields = {
            "spoken": "authorized voice test",
            "audio_base64": request_audio,
            "audio_mime_type": "audio/wav",
            "audio_filename": "test.wav",
        }

        preview = client.post(
            f"/api/targets/{target['id']}/preview",
            json={"adapter": "voice-transcript", "fields": fields},
        )
        assert preview.status_code == 200
        assert request_audio not in preview.text
        assert "audio omitted" in preview.text

        response = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target["id"],
                "adapter": "voice-transcript",
                "fields": fields,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["analysis"]["verdict"] == "confirmed_violation"
        assert requests[0]["audio"]["data"] == request_audio
        metadata = result["metadata"]["exchange"]["response_metadata"]
        assert metadata["response_audio_url"] == f"/api/runs/{result['run_id']}/audio"
        assert "response_audio_data_url" not in metadata
        audio_response = client.get(metadata["response_audio_url"])
        assert audio_response.status_code == 200
        assert audio_response.headers["content-type"] == "audio/wav"
        assert audio_response.content == b"RIFF-test-response"
        assert response_audio not in result["metadata"]["exchange"]["raw_response"]
        assert request_audio not in result["script"]
        assert result["metadata"]["channel"]["body"]["audio_attachment"][
            "filename"
        ] == "test.wav"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_voice_target_requires_https_outside_loopback(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    response = client.post(
        "/api/targets",
        json={
            "name": "Unsafe voice service",
            "environment": "staging",
            "connector": "voice",
            "endpoint": "http://voice.example.com/interact",
            "response_path": "transcript",
        },
    )
    assert response.status_code == 422


def test_streaming_voice_target_frames_audio_and_collects_events(tmp_path, monkeypatch):
    sent = []
    response_chunk = base64.b64encode(b"spoken-response").decode()

    class FakeSocket:
        def close(self):
            return None

    class FakeStreamConnection:
        def __init__(self):
            self.responses = iter(
                [
                    json.dumps(
                        {
                            "type": "response.delta",
                            "transcript_delta": "VOICE-",
                            "audio_delta": response_chunk,
                            "actions": [
                                {"name": "disclose_record", "arguments": {}}
                            ],
                        }
                    ),
                    json.dumps(
                        {
                            "type": "session.done",
                            "transcript_delta": "STREAM",
                        }
                    ),
                ]
            )

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send(self, payload):
            sent.append(json.loads(payload))

        def recv(self, timeout):
            assert timeout > 0
            return next(self.responses)

    monkeypatch.setattr(connectors, "_resolve_destination", lambda *_args, **_kwargs: "127.0.0.1")
    monkeypatch.setattr(connectors.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket())
    monkeypatch.setattr(connectors, "websocket_connect", lambda *_args, **_kwargs: FakeStreamConnection())

    client = TestClient(create_app(tmp_path / "runs.db"))
    target = client.post(
        "/api/targets",
        json={
            "name": "Realtime voice gateway",
            "environment": "staging",
            "connector": "voice-stream",
            "endpoint": "ws://127.0.0.1:8765/media",
            "request_template": (
                '{"type":"session.start","id":"{{message_id}}",'
                '"transcript":"{{input}}","mime":"{{audio_mime_type}}"}'
            ),
            "response_path": "transcript_delta",
            "actions_path": "actions",
            "voice_response_audio_path": "audio_delta",
            "voice_response_audio_type": "audio/wav",
            "voice_stream_chunk_bytes": 1024,
            "voice_stream_max_events": 10,
            "evidence": {
                "response_markers": ["VOICE-STREAM"],
                "forbidden_tools": ["disclose_record"],
            },
        },
    ).json()
    request_audio_bytes = b"A" * 2500
    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": target["id"],
            "adapter": "voice-transcript",
            "fields": {
                "spoken": "authorized stream test",
                "audio_base64": base64.b64encode(request_audio_bytes).decode(),
                "audio_mime_type": "audio/wav",
                "audio_filename": "stream.wav",
            },
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["response_text"] == "VOICE-STREAM"
    assert result["analysis"]["verdict"] == "confirmed_violation"
    assert [event["type"] for event in sent] == [
        "session.start",
        "audio.chunk",
        "audio.chunk",
        "audio.chunk",
        "audio.end",
    ]
    assert sum(
        len(base64.b64decode(event["audio"]))
        for event in sent
        if event["type"] == "audio.chunk"
    ) == len(request_audio_bytes)
    audio_url = result["metadata"]["exchange"]["response_metadata"][
        "response_audio_url"
    ]
    assert client.get(audio_url).content == b"spoken-response"
    assert response_chunk not in result["metadata"]["exchange"]["raw_response"]


def test_streaming_voice_sends_cancel_when_event_limit_is_reached(tmp_path, monkeypatch):
    sent = []

    class FakeSocket:
        def close(self):
            return None

    class NeverDoneConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send(self, payload):
            sent.append(json.loads(payload))

        def recv(self, timeout):
            return json.dumps({"type": "response.delta", "text": "still running"})

    monkeypatch.setattr(connectors, "_resolve_destination", lambda *_args, **_kwargs: "127.0.0.1")
    monkeypatch.setattr(connectors.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket())
    monkeypatch.setattr(connectors, "websocket_connect", lambda *_args, **_kwargs: NeverDoneConnection())

    client = TestClient(create_app(tmp_path / "runs.db"))
    target = client.post(
        "/api/targets",
        json={
            "name": "Bounded realtime gateway",
            "environment": "staging",
            "connector": "voice-stream",
            "endpoint": "ws://127.0.0.1:8765/media",
            "request_template": '{"type":"session.start"}',
            "response_path": "text",
            "voice_stream_max_events": 1,
        },
    ).json()
    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": target["id"],
            "adapter": "voice-transcript",
            "fields": {"spoken": "test"},
        },
    )
    assert response.status_code == 502
    assert "event limit" in response.json()["detail"]
    assert sent[-1]["type"] == "session.cancel"


def test_optical_target_sends_validated_image_and_captures_ocr_response(tmp_path):
    requests = []

    class OpticalHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            requests.append(json.loads(self.rfile.read(length)))
            body = json.dumps(
                {
                    "text": "OCR-MARKER",
                    "actions": [{"name": "release_parcel", "arguments": {}}],
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    image_buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(image_buffer, format="PNG")
    image_base64 = base64.b64encode(image_buffer.getvalue()).decode()
    server = ThreadingHTTPServer(("127.0.0.1", 0), OpticalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "Warehouse vision agent",
                "environment": "staging",
                "connector": "optical",
                "endpoint": f"http://127.0.0.1:{server.server_port}/analyze",
                "request_template": (
                    '{"instruction":"{{input}}","image":'
                    '{"data":"{{image_base64}}","type":"{{image_mime_type}}"}}'
                ),
                "response_path": "text",
                "actions_path": "actions",
                "evidence": {
                    "response_markers": ["OCR-MARKER"],
                    "forbidden_tools": ["release_parcel"],
                },
            },
        ).json()
        fields = {
            "text": "read this label",
            "image_base64": image_base64,
            "image_mime_type": "image/png",
            "image_filename": "label.png",
        }
        preview = client.post(
            f"/api/targets/{target['id']}/preview",
            json={"adapter": "text-in-image", "fields": fields},
        )
        assert preview.status_code == 200
        assert image_base64 not in preview.text
        assert "image omitted" in preview.text

        response = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target["id"],
                "adapter": "text-in-image",
                "fields": fields,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["analysis"]["verdict"] == "confirmed_violation"
        assert requests[0]["image"]["data"] == image_base64
        assert image_base64 not in result["script"]
        assert result["metadata"]["channel"]["body"]["image_attachment"][
            "filename"
        ] == "label.png"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_optical_upload_rejects_mime_mismatch(tmp_path):
    image_buffer = BytesIO()
    Image.new("RGB", (2, 2)).save(image_buffer, format="PNG")
    client = TestClient(create_app(tmp_path / "runs.db"))
    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": "missing-target",
            "adapter": "qr-code",
            "fields": {
                "text": "test",
                "image_base64": base64.b64encode(image_buffer.getvalue()).decode(),
                "image_mime_type": "image/jpeg",
                "image_filename": "mismatch.jpg",
            },
        },
    )
    assert response.status_code == 422


def test_device_bridge_requires_acknowledgement_and_always_stops(tmp_path):
    calls = []

    class BridgeHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            calls.append((self.path, json.loads(self.rfile.read(length))))
            if self.path == "/execute":
                payload = {
                    "response": "HARDWARE-MARKER",
                    "actions": [{"name": "advertise", "arguments": {}}],
                }
            else:
                payload = {"stopped": True}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "BLE lab bridge",
                "environment": "staging",
                "connector": "device-bridge",
                "endpoint": f"{origin}/execute",
                "hardware_stop_endpoint": f"{origin}/stop",
                "hardware_kind": "ble",
                "hardware_operation": "ble_advertise",
                "hardware_device_id": "bridge-01",
                "hardware_allowed_device_ids": ["bridge-01"],
                "hardware_resource": "advertisement-01",
                "hardware_allowed_resources": ["advertisement-01"],
                "hardware_duration_ms": 2500,
                "request_template": (
                    '{"device_id":"{{device_id}}","operation":"{{operation}}",'
                    '"resource":"{{resource}}","duration_ms":"{{duration_ms}}",'
                    '"input":"{{input}}"}'
                ),
                "response_path": "response",
                "actions_path": "actions",
                "evidence": {
                    "response_markers": ["HARDWARE-MARKER"],
                    "forbidden_tools": ["advertise"],
                },
            },
        ).json()
        request = {
            "target_id": target["id"],
            "adapter": "ble-advert",
            "fields": {"text": "authorized BLE injection test"},
        }
        blocked = client.post("/api/workbench/runs", json=request)
        assert blocked.status_code == 409

        request["production_acknowledged"] = True
        response = client.post("/api/workbench/runs", json=request)
        assert response.status_code == 200
        result = response.json()
        assert result["analysis"]["verdict"] == "confirmed_violation"
        assert [path for path, _body in calls] == ["/execute", "/stop"]
        assert calls[0][1]["device_id"] == "bridge-01"
        assert calls[0][1]["resource"] == "advertisement-01"
        assert calls[0][1]["duration_ms"] == 2500
        assert result["metadata"]["exchange"]["response_metadata"][
            "stop_confirmed"
        ] is True
        calls.clear()
        campaign = client.post(
            "/api/campaigns/runs",
            json={
                "target_id": target["id"],
                "adapter": "ble-advert",
                "fields_template": {"text": "{{position}}"},
                "payloads": ["one", "two"],
                "concurrency": 4,
                "production_acknowledged": True,
            },
        )
        assert campaign.status_code == 200
        assert campaign.json()["effective_concurrency"] == 1
        assert [path for path, _body in calls] == [
            "/execute",
            "/stop",
            "/execute",
            "/stop",
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_device_bridge_sends_stop_after_action_failure(tmp_path):
    calls = []

    class FailingBridgeHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            self.rfile.read(length)
            calls.append(self.path)
            if self.path == "/execute":
                self.send_response(302)
                self.send_header("location", "/elsewhere")
                self.end_headers()
                return
            body = b'{"stopped":true}'
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FailingBridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "GPIO lab bridge",
                "environment": "staging",
                "connector": "device-bridge",
                "endpoint": f"{origin}/execute",
                "hardware_stop_endpoint": f"{origin}/stop",
                "hardware_kind": "gpio",
                "hardware_operation": "gpio_sequence",
                "hardware_device_id": "gpio-01",
                "hardware_allowed_device_ids": ["gpio-01"],
                "hardware_resource": "pin-17",
                "hardware_allowed_resources": ["pin-17"],
            },
        ).json()
        response = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target["id"],
                "adapter": "binary-toggle",
                "fields": {"bits": "1010"},
                "production_acknowledged": True,
            },
        )
        assert response.status_code == 502
        assert "redirect" in response.json()["detail"]
        assert calls == ["/execute", "/stop"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_led_rig_captures_out_of_band_http_observation(tmp_path):
    calls = []
    state = {"active": False}

    class RigHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            payload = {
                "text": "LIGHT-MARKER" if state["active"] else "idle",
                "actions": (
                    [{"name": "unlock_gate", "arguments": {}}]
                    if state["active"]
                    else []
                ),
            }
            self._respond(payload)

        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            request = json.loads(self.rfile.read(length))
            calls.append(self.path)
            if self.path == "/execute":
                state["active"] = True
                assert request["input"]["blink_units"]
                self._respond({"emitted": True})
            else:
                state["active"] = False
                self._respond({"stopped": True})

        def _respond(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), RigHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        client = TestClient(create_app(tmp_path / "runs.db"))
        target = client.post(
            "/api/targets",
            json={
                "name": "LED sensor rig",
                "environment": "staging",
                "connector": "device-bridge",
                "endpoint": f"{origin}/execute",
                "hardware_stop_endpoint": f"{origin}/stop",
                "hardware_kind": "led",
                "hardware_operation": "led_sequence",
                "hardware_device_id": "arduino-01",
                "hardware_allowed_device_ids": ["arduino-01"],
                "hardware_resource": "pin-9",
                "hardware_allowed_resources": ["pin-9"],
                "request_template": (
                    '{"device_id":"{{device_id}}","operation":"{{operation}}",'
                    '"resource":"{{resource}}","input":"{{body}}"}'
                ),
                "observer_kind": "http",
                "observer_url": f"{origin}/observer",
                "observer_wait_ms": 0,
                "response_path": "text",
                "actions_path": "actions",
                "evidence": {
                    "response_markers": ["LIGHT-MARKER"],
                    "forbidden_tools": ["unlock_gate"],
                },
            },
        )
        assert target.status_code == 201
        response = client.post(
            "/api/workbench/runs",
            json={
                "target_id": target.json()["id"],
                "adapter": "morse-blink",
                "fields": {"signal": "SOS"},
                "production_acknowledged": True,
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert response.status_code == 200
    result = response.json()
    assert calls == ["/observer", "/execute", "/observer", "/stop"]
    assert result["response_text"] == "LIGHT-MARKER"
    assert result["analysis"]["verdict"] == "confirmed_violation"
    observation = result["metadata"]["exchange"]["response_metadata"][
        "observation"
    ]
    assert observation["before"]["text"] == "idle"
    assert observation["after"]["text"] == "LIGHT-MARKER"
    assert state["active"] is False


def test_device_bridge_rejects_non_allowlisted_resource(tmp_path):
    client = TestClient(create_app(tmp_path / "runs.db"))
    response = client.post(
        "/api/targets",
        json={
            "name": "Unsafe NFC bridge",
            "environment": "staging",
            "connector": "device-bridge",
            "endpoint": "http://127.0.0.1:9000/execute",
            "hardware_stop_endpoint": "http://127.0.0.1:9000/stop",
            "hardware_kind": "nfc",
            "hardware_operation": "nfc_emulate",
            "hardware_device_id": "nfc-01",
            "hardware_allowed_device_ids": ["nfc-01"],
            "hardware_resource": "tag-slot-99",
            "hardware_allowed_resources": ["tag-slot-01"],
        },
    )
    assert response.status_code == 422
