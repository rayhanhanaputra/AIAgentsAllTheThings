#!/usr/bin/env python3
"""Live AgriBot agent for the smart-farm simulator.

Subscribes to the soil-telemetry topic on an MQTT broker, runs each reading through
the harness target and the valve-policy oracle, and prints the decision and any
policy violation. This is the receiving half of the live demo; publish readings with
sensor.py.

Environment:
  MQTT_HOST     broker host (default: localhost)
  MQTT_PORT     broker port (default: 1883)
  MITIGATIONS   comma-separated subset of
                freetext_quarantine,schema_validation,policy_gate (default: none)
  AAT_TARGET    agribot-mock (default) or agribot-llm
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paho.mqtt.client as mqtt

from harness.core import registry
from harness.core.types import Message

HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
MITIGATIONS = frozenset(m for m in os.getenv("MITIGATIONS", "").split(",") if m)
TARGET_NAME = os.getenv("AAT_TARGET", "agribot-mock")


def main() -> int:
    scenario = registry.get("scenario", "smartfarm-irrigation")()
    target = registry.get("target", TARGET_NAME)(scenario.policy, MITIGATIONS)
    oracle = registry.get("oracle", "valve_policy")()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(scenario.topic, qos=1)
        print(f"AgriBot online. topic={scenario.topic} "
              f"mitigations={sorted(MITIGATIONS) or 'none'}", flush=True)

    def on_message(client, userdata, msg):
        try:
            body = json.loads(msg.payload.decode())
            if not isinstance(body, dict):
                raise ValueError("payload is not a JSON object")
        except ValueError as exc:
            print(f"! dropped malformed message on {msg.topic}: {exc}", flush=True)
            return
        try:
            target.reset()
            target.handle(Message(msg_id=body.get("msg_id", "live"), topic=msg.topic, body=body))
            verdict = oracle.evaluate(target.actions, scenario)
        except Exception as exc:  # never let one message crash the agent loop
            print(f"! error handling message on {msg.topic}: {exc}", flush=True)
            return
        for a in target.actions:
            print(f"  decision: {a.tool} {a.args} ({a.note})", flush=True)
        if verdict.success:
            print(f"  ALERT policy violation: {verdict.reason}", flush=True)
        else:
            print(f"  ok: {verdict.reason}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(HOST, PORT, keepalive=30)
    except OSError as exc:
        print(f"error: cannot reach MQTT broker at {HOST}:{PORT} ({exc}). "
              f"Start one with: cd sims/smartfarm && docker compose up -d", file=sys.stderr)
        return 2
    client.loop_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
