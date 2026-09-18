"""Run the real Workbench API against every local dummy connector."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable

from fastapi.testclient import TestClient
from PIL import Image

from harness.api.app import create_app


CHANNELS: Dict[str, Dict[str, Any]] = {
    "prompt-text": {"prompt": "AAT e2e prompt"},
    "json-field": {"note": "AAT e2e JSON"},
    "sensor-value": {"level": 42, "note": "AAT e2e sensor"},
    "reading-stream": {"window": [1, 0, 1]},
    "binary-toggle": {"bits": "1010"},
    "morse-blink": {"signal": "SOS"},
    "voice-transcript": {"spoken": "AAT e2e voice", "dtmf": "1"},
    "qr-code": {"text": "AAT e2e QR"},
    "text-in-image": {"text": "AAT e2e OCR"},
    "agent-note": {"text": "AAT e2e agent note"},
    "retrieved-doc": {"text": "AAT e2e retrieved document"},
    "ble-advert": {"text": "AAT e2e BLE"},
    "nfc-tag": {"text": "AAT e2e NFC"},
}
GENERAL_CONNECTORS = ("http", "tcp", "mqtt", "websocket")
MARKER = "AAT-E2E-OK"
HTTP_PORT = int(os.environ.get("AAT_DUMMY_HTTP_PORT", "9101"))
TCP_PORT = int(os.environ.get("AAT_DUMMY_TCP_PORT", "9102"))
MQTT_PORT = int(os.environ.get("AAT_DUMMY_MQTT_PORT", "18883"))
WEBSOCKET_PORT = int(os.environ.get("AAT_DUMMY_WS_PORT", "9103"))
VOICE_WEBSOCKET_PORT = int(os.environ.get("AAT_DUMMY_VOICE_WS_PORT", "9104"))


def _png_attachment() -> Dict[str, Any]:
    output = BytesIO()
    Image.new("RGB", (2, 2), color=(239, 140, 99)).save(output, format="PNG")
    return {
        "image_base64": base64.b64encode(output.getvalue()).decode(),
        "image_mime_type": "image/png",
        "image_filename": "e2e.png",
    }


def _base_profile(name: str, connector: str) -> Dict[str, Any]:
    value: Dict[str, Any] = {
        "name": name,
        "environment": "staging",
        "connector": connector,
        "request_template": '"{{message}}"',
        "response_path": "answer",
        "actions_path": "actions",
        "evidence": {"response_markers": [MARKER], "forbidden_tools": []},
        "timeout_seconds": 5,
    }
    if connector == "http":
        value["endpoint"] = f"http://127.0.0.1:{HTTP_PORT}/agent"
    elif connector == "tcp":
        value.update({"host": "127.0.0.1", "port": TCP_PORT})
    elif connector == "mqtt":
        value.update(
            {
                "host": "127.0.0.1",
                "port": MQTT_PORT,
                "mqtt_publish_topic": "aat/e2e/requests",
                "mqtt_response_topic": "aat/e2e/responses/{{message_id}}",
                "mqtt_qos": 1,
            }
        )
    elif connector == "websocket":
        value["endpoint"] = f"ws://127.0.0.1:{WEBSOCKET_PORT}/agent"
    return value


def _create(client: TestClient, profile: Dict[str, Any]) -> str:
    response = client.post("/api/targets", json=profile)
    if response.status_code != 201:
        raise RuntimeError(f"cannot create {profile['name']}: {response.text}")
    return response.json()["id"]


def _run(
    client: TestClient,
    target_id: str,
    adapter: str,
    fields: Dict[str, Any],
    *,
    marker_required: bool = True,
    production_acknowledged: bool = False,
) -> tuple[bool, str]:
    response = client.post(
        "/api/workbench/runs",
        json={
            "target_id": target_id,
            "adapter": adapter,
            "fields": fields,
            "production_acknowledged": production_acknowledged,
        },
    )
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:240]}"
    result = response.json()
    if result["state"] != "completed":
        return False, f"state={result['state']}"
    if marker_required and MARKER not in result["response_text"]:
        return False, "dummy marker absent from captured response"
    return True, result["run_id"]


def run_matrix() -> Dict[str, Any]:
    results: list[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="aat-e2e-") as directory:
        client = TestClient(create_app(Path(directory) / "workbench.db"))
        simulator = next(
            target for target in client.get("/api/targets").json()["targets"]
            if target["connector"] == "simulator"
        )
        for adapter, fields in CHANNELS.items():
            passed, detail = _run(
                client, simulator["id"], adapter, fields, marker_required=False
            )
            results.append(_case("simulator", adapter, passed, detail))

        for connector in GENERAL_CONNECTORS:
            target_id = _create(client, _base_profile(f"Dummy {connector}", connector))
            for adapter, fields in CHANNELS.items():
                passed, detail = _run(client, target_id, adapter, fields)
                results.append(_case(connector, adapter, passed, detail))

        voice = _base_profile("Dummy voice", "voice")
        voice.update(
            {
                "endpoint": f"http://127.0.0.1:{HTTP_PORT}/voice",
                "request_template": '{"transcript":"{{input}}"}',
                "response_path": "transcript",
                "voice_response_audio_path": "audio_base64",
            }
        )
        passed, detail = _run(
            client,
            _create(client, voice),
            "voice-transcript",
            CHANNELS["voice-transcript"],
        )
        results.append(_case("voice", "voice-transcript", passed, detail))

        voice_stream = _base_profile("Dummy voice stream", "voice-stream")
        voice_stream.update(
            {
                "endpoint": f"ws://127.0.0.1:{VOICE_WEBSOCKET_PORT}/voice",
                "request_template": '{"type":"session.start","transcript":"{{input}}"}',
                "response_path": "transcript_delta",
                "voice_response_audio_path": None,
            }
        )
        passed, detail = _run(
            client,
            _create(client, voice_stream),
            "voice-transcript",
            CHANNELS["voice-transcript"],
        )
        results.append(_case("voice-stream", "voice-transcript", passed, detail))

        optical = _base_profile("Dummy optical", "optical")
        optical.update(
            {
                "endpoint": f"http://127.0.0.1:{HTTP_PORT}/optical",
                "request_template": '{"instruction":"{{input}}","image":"{{image_base64}}"}',
                "response_path": "text",
            }
        )
        optical_id = _create(client, optical)
        for adapter in ("qr-code", "text-in-image"):
            fields = {**CHANNELS[adapter], **_png_attachment()}
            passed, detail = _run(client, optical_id, adapter, fields)
            results.append(_case("optical", adapter, passed, detail))

        device_cases: Iterable[tuple[str, str, str, str]] = (
            ("ble", "ble_advertise", "ble-advert", "advertisement-01"),
            ("nfc", "nfc_emulate", "nfc-tag", "tag-slot-01"),
            ("gpio", "gpio_sequence", "binary-toggle", "pin-17"),
            ("gpio", "gpio_sequence", "morse-blink", "pin-17"),
        )
        for kind, operation, adapter, resource in device_cases:
            device = _base_profile(f"Dummy {kind} {adapter}", "device-bridge")
            device.update(
                {
                    "endpoint": f"http://127.0.0.1:{HTTP_PORT}/bridge/action",
                    "hardware_stop_endpoint": f"http://127.0.0.1:{HTTP_PORT}/bridge/stop",
                    "hardware_kind": kind,
                    "hardware_operation": operation,
                    "hardware_device_id": "bridge-01",
                    "hardware_allowed_device_ids": ["bridge-01"],
                    "hardware_resource": resource,
                    "hardware_allowed_resources": [resource],
                    "request_template": '{"device_id":"{{device_id}}","operation":"{{operation}}","resource":"{{resource}}","input":"{{input}}"}',
                    "response_path": "response",
                }
            )
            passed, detail = _run(
                client,
                _create(client, device),
                adapter,
                CHANNELS[adapter],
                production_acknowledged=True,
            )
            results.append(_case("device-bridge", adapter, passed, detail, kind))

        os.environ["AAT_DUMMY_MAPPER_KEY"] = "dummy-mapper-key"
        mapped = _base_profile("Dummy mapped HTTP", "http")
        mapped.update(
            {
                "endpoint": f"http://127.0.0.1:{HTTP_PORT}/agent",
                "request_template": '"{{mapped}}"',
                "mapper_enabled": True,
                "mapper_endpoint": f"http://127.0.0.1:{HTTP_PORT}/v1/chat/completions",
                "mapper_model": "dummy-mapper",
                "mapper_api_key_env": "AAT_DUMMY_MAPPER_KEY",
                "mapper_instructions": "Return command and parameters for the dummy target.",
                "mapper_required_keys": ["command", "parameters"],
            }
        )
        passed, detail = _run(
            client,
            _create(client, mapped),
            "sensor-value",
            CHANNELS["sensor-value"],
        )
        results.append(_case("http+llm-mapper", "sensor-value", passed, detail))

        os.environ["AAT_DUMMY_RESPONSE_MAPPER_KEY"] = "dummy-mapper-key"
        response_mapped = _base_profile("Dummy response-mapped HTTP", "http")
        response_mapped.update(
            {
                "endpoint": f"http://127.0.0.1:{HTTP_PORT}/agent",
                "response_path": "answer",
                "response_mapper_enabled": True,
                "response_mapper_endpoint": (
                    f"http://127.0.0.1:{HTTP_PORT}/v1/chat/completions"
                ),
                "response_mapper_model": "dummy-response-mapper",
                "response_mapper_api_key_env": "AAT_DUMMY_RESPONSE_MAPPER_KEY",
                "response_mapper_instructions": (
                    "Preserve the visible answer and observed actions."
                ),
            }
        )
        passed, detail = _run(
            client,
            _create(client, response_mapped),
            "prompt-text",
            CHANNELS["prompt-text"],
        )
        results.append(
            _case("http+llm-response-mapper", "prompt-text", passed, detail)
        )

    passed_count = sum(case["status"] == "PASS" for case in results)
    return {
        "summary": {
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "supported_cases": len(results),
            "unsupported_policy": "N/A by design; media/device-specific connectors only run compatible channels",
        },
        "cases": results,
    }


def _case(
    connector: str, adapter: str, passed: bool, detail: str, variant: str | None = None
) -> Dict[str, Any]:
    return {
        "connector": connector,
        "channel_adapter": adapter,
        "variant": variant,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


if __name__ == "__main__":
    report = run_matrix()
    output = Path("out/workbench-e2e-report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    raise SystemExit(1 if report["summary"]["failed"] else 0)
