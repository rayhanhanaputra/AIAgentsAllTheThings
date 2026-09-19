# Workbench backend runtime

`harness/` is the Python runtime behind the Web Workbench:

| Path | Role |
| --- | --- |
| `api/` | Local API, target profiles, connectors, mappers, evidence, and history |
| `encoders/` | Canonical input-channel adapters |
| `hardware/` | Guarded Arduino/ESP32 bridge |
| `core/` | Channel message types and encoder registry |

Start the API with `python3 -m harness.api` or `make workbench-api`. Connector fixtures
live under `tests/fixtures/`; intentionally vulnerable visual simulations live in the
separate AIAgentsAllTheThings-SimLab project.
