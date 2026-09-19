import json
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading

import pytest

from harness.hardware.arduino_bridge import (
    BridgeError,
    LedController,
    create_handler,
)


def simulated_controller():
    return LedController(
        device_id="arduino-01",
        pin=9,
        serial_port=None,
        baud=115_200,
        simulate=True,
    )


def test_led_controller_accepts_bounded_blink_units_and_stops():
    controller = simulated_controller()
    result = controller.run(
        {
            "device_id": "arduino-01",
            "operation": "led_sequence",
            "resource": "pin-9",
            "duration_ms": 2_000,
            "unit_ms": 100,
            "input": {"blink_units": [["on", 1], ["off", 3]]},
        }
    )

    assert result["accepted"] is True
    assert result["duration_ms"] == 400
    assert controller.stop(
        {"device_id": "arduino-01", "resource": "pin-9"}
    )["stopped"] is True
    assert controller.last_command == {"command": "stop", "pin": 9}


@pytest.mark.parametrize(
    "change",
    [
        {"device_id": "other"},
        {"resource": "pin-10"},
        {"operation": "serial_shell"},
        {"input": {"blink_units": [["on", 100]]}},
    ],
)
def test_led_controller_rejects_unallowlisted_or_unbounded_commands(change):
    request = {
        "device_id": "arduino-01",
        "operation": "led_sequence",
        "resource": "pin-9",
        "duration_ms": 2_000,
        "unit_ms": 100,
        "input": {"blink_units": [["on", 1], ["off", 1]]},
    }
    request.update(change)

    with pytest.raises(BridgeError):
        simulated_controller().run(request)


@contextmanager
def bridge_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(simulated_controller()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bridge_exposes_health_action_and_stop_endpoints():
    with bridge_server() as port:
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/health")
        assert json.loads(connection.getresponse().read())["simulate"] is True

        action = json.dumps(
            {
                "device_id": "arduino-01",
                "operation": "led_sequence",
                "resource": "pin-9",
                "input": {"blink_units": [["on", 1], ["off", 1]]},
            }
        )
        connection.request(
            "POST", "/action", body=action, headers={"content-type": "application/json"}
        )
        assert json.loads(connection.getresponse().read())["accepted"] is True

        stop = json.dumps({"device_id": "arduino-01", "resource": "pin-9"})
        connection.request(
            "POST", "/stop", body=stop, headers={"content-type": "application/json"}
        )
        assert json.loads(connection.getresponse().read())["stopped"] is True
        connection.close()
