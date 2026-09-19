"""Loopback HTTP-to-serial bridge for an allowlisted Arduino/ESP32 LED rig."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

MAX_BODY_BYTES = 64 * 1024
MAX_STEPS = 256
MAX_DURATION_MS = 30_000

try:
    import serial
except ImportError:  # pragma: no cover - exercised by installations without hardware extra.
    serial = None


class BridgeError(ValueError):
    """A bounded error safe to return to a local bridge client."""


class LedController:
    def __init__(
        self,
        *,
        device_id: str,
        pin: int,
        serial_port: str | None,
        baud: int,
        simulate: bool,
    ) -> None:
        self.device_id = device_id
        self.pin = pin
        self.simulate = simulate
        self.lock = threading.Lock()
        self.connection = None
        self.last_command: Dict[str, Any] | None = None
        if not simulate:
            if serial is None:
                raise RuntimeError(
                    "Arduino bridge requires pyserial; install the 'hardware' extra"
                )
            if not serial_port:
                raise RuntimeError("--serial-port is required unless --simulate is used")
            self.connection = serial.Serial(
                serial_port,
                baudrate=baud,
                timeout=3,
                write_timeout=3,
            )

    def run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_identity(request)
        if request.get("operation") != "led_sequence":
            raise BridgeError("only led_sequence is supported")
        input_value = request.get("input")
        if not isinstance(input_value, dict):
            raise BridgeError("input must contain the encoded channel object")
        raw_steps = input_value.get("blink_units")
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
            raise BridgeError("blink_units must contain 1-256 steps")
        unit_ms = request.get("unit_ms", 200)
        if not isinstance(unit_ms, int) or not 50 <= unit_ms <= 2_000:
            raise BridgeError("unit_ms must be an integer from 50 to 2000")
        steps = _validated_steps(raw_steps)
        duration_ms = sum(item["units"] * unit_ms for item in steps)
        requested_limit = request.get("duration_ms", MAX_DURATION_MS)
        if not isinstance(requested_limit, int):
            raise BridgeError("duration_ms must be an integer")
        if duration_ms > min(requested_limit, MAX_DURATION_MS):
            raise BridgeError("LED sequence exceeds the configured duration limit")
        command = {
            "command": "led_sequence",
            "pin": self.pin,
            "unit_ms": unit_ms,
            "steps": steps,
            "watchdog_ms": min(requested_limit, MAX_DURATION_MS),
        }
        reply = self._send(command)
        return {
            "accepted": True,
            "device_id": self.device_id,
            "resource": f"pin-{self.pin}",
            "duration_ms": duration_ms,
            "controller": reply,
        }

    def stop(self, request: Dict[str, Any]) -> Dict[str, Any]:
        self._validate_identity(request)
        reply = self._send({"command": "stop", "pin": self.pin})
        return {"stopped": True, "device_id": self.device_id, "controller": reply}

    def _validate_identity(self, request: Dict[str, Any]) -> None:
        if request.get("device_id") != self.device_id:
            raise BridgeError("device_id is not allowlisted")
        if request.get("resource") != f"pin-{self.pin}":
            raise BridgeError("resource is not allowlisted")

    def _send(self, command: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            self.last_command = command
            if self.simulate:
                return {"status": "ok", "simulated": True}
            assert self.connection is not None
            self.connection.reset_input_buffer()
            self.connection.write((json.dumps(command, separators=(",", ":")) + "\n").encode())
            self.connection.flush()
            line = self.connection.readline(MAX_BODY_BYTES)
            if not line:
                raise BridgeError("controller did not acknowledge the command")
            try:
                reply = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BridgeError("controller returned invalid JSON") from exc
            if not isinstance(reply, dict) or reply.get("status") != "ok":
                raise BridgeError("controller rejected the command")
            return reply


def _validated_steps(raw_steps: List[Any]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, list) or len(item) != 2:
            raise BridgeError("each blink step must be [state, units]")
        state, units = item
        if state not in {"on", "off"}:
            raise BridgeError("blink state must be on or off")
        if not isinstance(units, int) or not 1 <= units <= 20:
            raise BridgeError("blink units must be an integer from 1 to 20")
        steps.append({"state": state, "units": units})
    return steps


def create_handler(controller: LedController):
    class ArduinoBridgeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                self._json(404, {"error": "not found"})
                return
            self._json(
                200,
                {
                    "status": "ok",
                    "device_id": controller.device_id,
                    "resource": f"pin-{controller.pin}",
                    "simulate": controller.simulate,
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/action", "/stop"}:
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("content-length", "0"))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise BridgeError("request body must be 1-65536 bytes")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise BridgeError("request body must be a JSON object")
                result = (
                    controller.run(request)
                    if self.path == "/action"
                    else controller.stop(request)
                )
                self._json(200, result)
            except (BridgeError, json.JSONDecodeError, ValueError) as exc:
                self._json(400, {"error": str(exc)})

        def _json(self, status: int, value: Dict[str, Any]) -> None:
            payload = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return ArduinoBridgeHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the guarded Arduino LED bridge")
    parser.add_argument("--serial-port")
    parser.add_argument("--baud", type=int, default=115_200)
    parser.add_argument("--device-id", default="arduino-01")
    parser.add_argument("--pin", type=int, default=9)
    parser.add_argument("--http-port", type=int, default=9910)
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.pin <= 99:
        parser.error("--pin must be from 0 to 99")
    controller = LedController(
        device_id=args.device_id,
        pin=args.pin,
        serial_port=args.serial_port,
        baud=args.baud,
        simulate=args.simulate,
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.http_port), create_handler(controller)
    )
    print(
        json.dumps(
            {
                "status": "ready",
                "url": f"http://127.0.0.1:{args.http_port}",
                "device_id": args.device_id,
                "resource": f"pin-{args.pin}",
                "simulate": args.simulate,
            }
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
