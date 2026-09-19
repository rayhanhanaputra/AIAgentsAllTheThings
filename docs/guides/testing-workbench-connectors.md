# Testing Workbench connectors

The test suite includes loopback-only fixtures for every connector. They
return `AAT-E2E-OK`, echo the received request shape, and never contact a real
agent.

For the automated connector matrix, run these in separate terminals:

```bash
make connector-fixtures
make workbench-e2e
```

The E2E command exercises 63 supported paths and writes the ignored report to
`out/workbench-e2e-report.json`.

| Connector | Fixture address | Supported channel tests |
| --- | --- | --- |
| HTTP | `http://127.0.0.1:9101/agent` | All 13 adapters |
| TCP | `127.0.0.1:9102` | All 13 adapters |
| MQTT | `127.0.0.1:18883` | All 13 adapters |
| WebSocket | `ws://127.0.0.1:9103/agent` | All 13 adapters |
| Voice HTTP | `http://127.0.0.1:9101/voice` | Voice transcript/audio |
| Voice stream | `ws://127.0.0.1:9104/voice` | Voice transcript/audio |
| Optical | `http://127.0.0.1:9101/optical` | QR and OCR image |
| Device bridge | `/bridge/action` and `/bridge/stop` on port `9101` | BLE, NFC, binary, Morse |
| Physical LED rig | Device bridge plus `/observer` | Morse LED stimulus plus out-of-band state |

The fixture OpenAI-compatible mapper is
`http://127.0.0.1:9101/v1/chat/completions`. Set
`AAT_DUMMY_MAPPER_KEY=dummy-mapper-key` in the API process, select **Use an LLM
input mapper**, and reference `AAT_DUMMY_MAPPER_KEY`—never paste the key into
the UI. Use `"{{mapped}}"` as the request template. The same endpoint also acts as
a deterministic response mapper when its request contains captured response evidence.

## Manual end-to-end test through the Web Workbench

Start three processes, one per terminal:

```bash
make connector-fixtures
AAT_DUMMY_MAPPER_KEY=dummy-mapper-key \
AAT_DUMMY_RESPONSE_MAPPER_KEY=dummy-mapper-key make workbench-api
make workbench-web
```

Then perform the same business flow a real assessment uses:

1. Open the web interface at `http://127.0.0.1:3417`.
2. Create a staging target profile using one fixture address from the table.
3. Choose an input adapter in **Workbench** and edit its decoded fields.
4. Confirm the encoded input and wire preview match the target contract.
5. Send the run and inspect the captured request, response, events, and verdict.
6. Repeat in **Campaigns** with several payloads and select every result row to inspect
   its own request and response.
7. Open **History** and verify that selecting a run loads that run's retained evidence.

For production-labelled profiles, the UI requires explicit authorization
acknowledgement for every run. Production campaigns are deliberately serialized.

## Input mapper test

Point the mapper URL at the fixture OpenAI-compatible endpoint, select **Use an LLM input
mapper**, reference `AAT_DUMMY_MAPPER_KEY`, and use `"{{mapped}}"` as the request
template. The retained run should contain both the mapped request and the connector
exchange without exposing the key value.

Prefer a normal request template for deterministic format conversion. Enable
the mapper only when the target contract cannot be expressed reliably as a
template. Mapper output is untrusted JSON: it is size-bounded, checked for
required keys, retained in run evidence, and fails closed.

## Response mapper test

Select **Normalize target responses with an LLM mapper**, use the fixture mapper URL,
and reference `AAT_DUMMY_RESPONSE_MAPPER_KEY`. After a run, **Messages** shows the
normalized response, **Events** identifies the mapping stage, and **Raw** retains the
original connector response plus the normalized metadata. Stop or misconfigure the
mapper to verify that the run records the failure and displays deterministic extraction.
