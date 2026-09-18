#!/usr/bin/env python3
"""Soil-sensor publisher for the smart-farm simulator.

Publishes telemetry to the broker. In benign mode it publishes a healthy reading; in
attack mode it publishes one of the payloads from the harness library, reproducing a
compromised or spoofed sensor. This is the sending half of the live demo; run agent.py
to observe the effect.

Environment: MQTT_HOST (default localhost), MQTT_PORT (default 1883).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt

from harness.core import registry

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))

PAYLOADS = {
    "benign": "smartfarm/benign-low-moisture",
    "note-override": "smartfarm/note-override@overt",
    "value-injection": "smartfarm/value-injection@out-of-range",
    "unauthorized-open": "smartfarm/note-override@sufficient-moisture",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attack", choices=sorted(PAYLOADS), default="benign",
                        help="which payload to publish (default: benign)")
    args = parser.parse_args()

    scenario = registry.get("scenario", "smartfarm-irrigation")()
    encoder = registry.get("encoder", "json-field")()
    payload = registry.get("payload", PAYLOADS[args.attack])
    message = encoder.encode(payload, scenario)
    body = dict(message.body, msg_id=message.msg_id)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(HOST, PORT, keepalive=30)
    except OSError as exc:
        print(f"error: cannot reach MQTT broker at {HOST}:{PORT} ({exc}). "
              f"Start one with: cd sims/smartfarm && docker compose up -d", file=sys.stderr)
        return 2
    client.publish(message.topic, json.dumps(body), qos=1)
    client.disconnect()
    print(f"published [{args.attack}] to {message.topic}: {json.dumps(body)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
