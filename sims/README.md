# Simulators

Virtual devices and target agents so a full attack loop runs locally without any
physical hardware. Real hardware is out of scope for this release; it would attach
behind the same transport interface (see `SECURITY.md`).

## Smart-farm irrigation (flagship, AAT-0001)

The live demo has three parts: an MQTT broker, the AgriBot agent, and the sensor
publisher.

### 1. Start the broker

```bash
cd sims/smartfarm
docker compose up -d          # Mosquitto on localhost:1883 (anonymous, lab-only)
```

### 2. Start the agent

From the repository root, in its own terminal:

```bash
pip install -r requirements.txt
python sims/smartfarm/agent.py                        # vulnerable agent
MITIGATIONS=freetext_quarantine,schema_validation,policy_gate python sims/smartfarm/agent.py   # hardened
```

### 3. Publish readings

In another terminal:

```bash
python sims/smartfarm/sensor.py --attack benign             # healthy reading
python sims/smartfarm/sensor.py --attack note-override       # instruction in the note field
python sims/smartfarm/sensor.py --attack value-injection     # out-of-range moisture
python sims/smartfarm/sensor.py --attack unauthorized-open   # open despite wet soil
```

Against the vulnerable agent the attacks produce a policy-violation ALERT; against the
hardened agent they do not, while benign irrigation still works.

### Offline and deterministic

The same scenario runs without a broker via the harness `direct` transport:

```bash
python -m harness.cli demo C2-I3-smartfarm-note-override
```

To drive a real model instead of the deterministic reference agent, set
`AAT_TARGET=agribot-llm` (requires the anthropic SDK and an API key).
