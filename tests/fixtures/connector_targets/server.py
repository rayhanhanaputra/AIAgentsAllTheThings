"""Local dummy agents for every Workbench connector.

These services only bind to loopback. They echo a deterministic marker and
record the incoming shape so users can validate request mapping safely.
"""

from __future__ import annotations

import argparse
import base64
import json
import signal
import socketserver
import struct
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from typing import Any, Dict

from websockets.sync.server import serve

MARKER = "AAT-E2E-OK"


def _wav_base64() -> str:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(struct.pack("<" + "h" * 160, *([0] * 160)))
    return base64.b64encode(output.getvalue()).decode()


SILENT_WAV = _wav_base64()


def _perceived(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("input", "prompt", "transcript", "scanned_text", "context", "advertised"):
        if key in value:
            return value[key]
    body = value.get("body")
    return _perceived(body) if isinstance(body, dict) else value


def _response(received: Any, connector: str) -> Dict[str, Any]:
    return {
        "answer": f"{MARKER} via {connector}: {_perceived(received)}",
        "transcript": f"{MARKER} voice response",
        "text": f"{MARKER} optical response",
        "response": f"{MARKER} bridge response",
        "audio_base64": SILENT_WAV,
        "received": received,
        "actions": [{"name": "dummy_observe", "arguments": {"connector": connector}}],
    }


class DummyState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[Dict[str, Any]] = []

    def add(self, connector: str, received: Any) -> None:
        with self.lock:
            self.events.append({"connector": connector, "received": received})

    def snapshot(self) -> list[Dict[str, Any]]:
        with self.lock:
            return list(self.events)

    def latest_connector(self) -> str | None:
        with self.lock:
            return self.events[-1]["connector"] if self.events else None


class DummyHttpHandler(BaseHTTPRequestHandler):
    state: DummyState

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "marker": MARKER})
        elif self.path == "/events":
            self._json(200, {"events": self.state.snapshot()})
        elif self.path == "/observer":
            active = self.state.latest_connector() == "device-bridge-action"
            self._json(
                200,
                {
                    "status": "agent processed physical signal" if active else "idle",
                    "text": f"{MARKER} observed LED stimulus" if active else "idle",
                    "actions": (
                        [
                            {
                                "name": "dummy_observe",
                                "arguments": {"channel": "light"},
                            }
                        ]
                        if active
                        else []
                    ),
                },
            )
        elif self.path == "/target-ui":
            active = self.state.latest_connector() == "device-bridge-action"
            text = f"{MARKER} observed LED stimulus" if active else "idle"
            body = (
                "<!doctype html><html><head><title>Dummy target UI</title></head>"
                f'<body><main data-testid="agent-response">{text}</main></body></html>'
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("content-length", "0"))
            received = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON"})
            return

        if self.path == "/v1/chat/completions":
            if self.headers.get("authorization") != "Bearer dummy-mapper-key":
                self._json(401, {"error": "dummy mapper key rejected"})
                return
            try:
                canonical = json.loads(received["messages"][-1]["content"])
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                self._json(400, {"error": "invalid mapper request"})
                return
            if "raw_response" in canonical:
                try:
                    raw = json.loads(canonical["raw_response"])
                except (TypeError, json.JSONDecodeError):
                    raw = {"answer": str(canonical["raw_response"]), "actions": []}
                mapped = {
                    "response_text": str(raw.get("answer", raw)),
                    "actions": raw.get("actions", []),
                    "events": [
                        {
                            "event_type": "dummy.response_observed",
                            "data": {"normalized": True},
                        }
                    ],
                    "metadata": {"mapper": "dummy-response-mapper"},
                }
                self.state.add("response-mapper", canonical)
                self._json(
                    200,
                    {"choices": [{"message": {"content": json.dumps(mapped)}}]},
                )
                return
            mapped = {
                "command": "inspect_input",
                "parameters": {
                    "source_topic": canonical.get("topic"),
                    "value": _perceived(canonical.get("body", {})),
                },
            }
            self.state.add("mapper", canonical)
            self._json(
                200,
                {"choices": [{"message": {"content": json.dumps(mapped)}}]},
            )
            return

        connector = {
            "/agent": "http",
            "/voice": "voice",
            "/optical": "optical",
            "/bridge/action": "device-bridge-action",
            "/bridge/stop": "device-bridge-stop",
        }.get(self.path)
        if connector is None:
            self._json(404, {"error": "not found"})
            return
        self.state.add(connector, received)
        self._json(200, _response(received, connector))

    def _json(self, status: int, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class DummyTcpHandler(socketserver.StreamRequestHandler):
    state: DummyState

    def handle(self) -> None:
        try:
            received = json.loads(self.rfile.readline(65_537))
        except json.JSONDecodeError:
            received = {"raw": "invalid JSON"}
        self.state.add("tcp", received)
        self.wfile.write((json.dumps(_response(received, "tcp")) + "\n").encode())


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def _generic_websocket(state: DummyState):
    def handler(connection: Any) -> None:
        received = json.loads(connection.recv())
        state.add("websocket", received)
        connection.send(json.dumps(_response(received, "websocket")))

    return handler


def _voice_websocket(state: DummyState):
    def handler(connection: Any) -> None:
        start = json.loads(connection.recv())
        chunks = 0
        while True:
            event = json.loads(connection.recv())
            if event.get("type") == "audio.chunk":
                chunks += 1
            if event.get("type") == "audio.end":
                break
        state.add("voice-stream", {"start": start, "chunks": chunks})
        connection.send(json.dumps({"type": "transcript", "transcript_delta": f"{MARKER} streamed voice"}))
        connection.send(json.dumps({"type": "session.done"}))

    return handler


def _mqtt_remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        encoded.append(digit)
        if not length:
            return bytes(encoded)


def _mqtt_packet(packet_type: int, flags: int, payload: bytes) -> bytes:
    return bytes([(packet_type << 4) | flags]) + _mqtt_remaining_length(len(payload)) + payload


class DummyMqttHandler(socketserver.StreamRequestHandler):
    """Tiny MQTT 3.1.1 broker implementing only this test contract."""

    state: DummyState

    def handle(self) -> None:
        response_topic = ""
        while True:
            first = self.rfile.read(1)
            if not first:
                return
            remaining = 0
            multiplier = 1
            while True:
                digit = self.rfile.read(1)
                if not digit:
                    return
                remaining += (digit[0] & 127) * multiplier
                if not digit[0] & 128:
                    break
                multiplier *= 128
            payload = self.rfile.read(remaining)
            packet_type = first[0] >> 4
            qos = (first[0] >> 1) & 0x03
            if packet_type == 1:  # CONNECT
                self.wfile.write(b"\x20\x02\x00\x00")
            elif packet_type == 8:  # SUBSCRIBE
                packet_id = payload[:2]
                topic_length = int.from_bytes(payload[2:4], "big")
                response_topic = payload[4 : 4 + topic_length].decode()
                requested_qos = payload[4 + topic_length]
                self.wfile.write(_mqtt_packet(9, 0, packet_id + bytes([requested_qos])))
            elif packet_type == 3:  # PUBLISH
                topic_length = int.from_bytes(payload[:2], "big")
                topic = payload[2 : 2 + topic_length].decode()
                offset = 2 + topic_length
                packet_id = payload[offset : offset + 2] if qos else b""
                if qos:
                    offset += 2
                    self.wfile.write(_mqtt_packet(4, 0, packet_id))
                try:
                    received = json.loads(payload[offset:])
                    message_id = received["msg_id"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                if topic != "aat/e2e/requests":
                    continue
                expected_topic = f"aat/e2e/responses/{message_id}"
                if response_topic != expected_topic:
                    continue
                self.state.add("mqtt", received)
                response = json.dumps(_response(received, "mqtt")).encode()
                variable = len(response_topic.encode()).to_bytes(2, "big") + response_topic.encode()
                variable += b"\x00\x01" + response
                self.wfile.write(_mqtt_packet(3, 2, variable))
            elif packet_type == 12:  # PINGREQ
                self.wfile.write(b"\xd0\x00")
            elif packet_type == 14:  # DISCONNECT
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run loopback Workbench dummy targets")
    parser.add_argument("--http-port", type=int, default=9101)
    parser.add_argument("--tcp-port", type=int, default=9102)
    parser.add_argument("--ws-port", type=int, default=9103)
    parser.add_argument("--voice-ws-port", type=int, default=9104)
    parser.add_argument("--mqtt-port", type=int, default=18883)
    args = parser.parse_args()

    state = DummyState()
    http_handler = type("BoundHttpHandler", (DummyHttpHandler,), {"state": state})
    tcp_handler = type("BoundTcpHandler", (DummyTcpHandler,), {"state": state})
    mqtt_handler = type("BoundMqttHandler", (DummyMqttHandler,), {"state": state})
    http_server = ThreadingHTTPServer(("127.0.0.1", args.http_port), http_handler)
    tcp_server = ThreadingTcpServer(("127.0.0.1", args.tcp_port), tcp_handler)
    mqtt_server = ThreadingTcpServer(("127.0.0.1", args.mqtt_port), mqtt_handler)
    threads = [
        threading.Thread(target=http_server.serve_forever, daemon=True),
        threading.Thread(target=tcp_server.serve_forever, daemon=True),
        threading.Thread(target=mqtt_server.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()

    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    with serve(_generic_websocket(state), "127.0.0.1", args.ws_port) as ws_server, serve(
        _voice_websocket(state), "127.0.0.1", args.voice_ws_port
    ) as voice_ws_server:
        ws_threads = [
            threading.Thread(target=ws_server.serve_forever, daemon=True),
            threading.Thread(target=voice_ws_server.serve_forever, daemon=True),
        ]
        for thread in ws_threads:
            thread.start()
        print(
            json.dumps(
                {
                    "status": "ready",
                    "http": f"http://127.0.0.1:{args.http_port}",
                    "tcp": f"127.0.0.1:{args.tcp_port}",
                    "websocket": f"ws://127.0.0.1:{args.ws_port}",
                    "voice_stream": f"ws://127.0.0.1:{args.voice_ws_port}",
                    "mqtt": f"127.0.0.1:{args.mqtt_port}",
                }
            ),
            flush=True,
        )
        while not stopping.wait(0.25):
            time.sleep(0)

    http_server.shutdown()
    tcp_server.shutdown()
    mqtt_server.shutdown()


if __name__ == "__main__":
    main()
