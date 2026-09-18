# Knowledge Base

The knowledge base is the browsable corpus of techniques for signal-to-prompt
injection against AI agents integrated with IoT and cyber-physical systems.

Entries are grouped by the **channel** that carries the injection. Within each
channel folder, the `README.md` is a Summary index of that channel's techniques.
The cross-tabulated Modality Injection Matrix (channel by intent), the machine
readable index, and the corpus statistics are **generated** from entry front matter
by `tools/build_registry.py` and live under [`registry/`](../registry/). Do not
hand-edit the generated files.

## Channels

| Channel | Folder | Scope |
| --- | --- | --- |
| C1 | [C1-sensor-value](C1-sensor-value/) | Spoofed, out-of-range, or overflowing numeric telemetry |
| C2 | [C2-data-field](C2-data-field/) | Instructions hidden in structured fields parsed as text |
| C3 | [C3-actuator-state](C3-actuator-state/) | Binary toggles, Morse, timing patterns the agent observes |
| C4 | [C4-voice-dtmf](C4-voice-dtmf/) | Adversarial speech, DTMF tones, ASR confusion |
| C5 | [C5-optical-visual](C5-optical-visual/) | QR, barcodes, text-in-image, steganography |
| C6 | [C6-rf-protocol](C6-rf-protocol/) | BLE, Zigbee, LoRa, NFC frames |
| C7 | [C7-indirect-inter-agent](C7-indirect-inter-agent/) | Poisoned logs, transcripts, tool outputs, retrieved documents |
| C8 | [C8-feedback-loop](C8-feedback-loop/) | Replay, flooding, timing races on a control loop |

See the [Modality Injection Matrix](../registry/matrix.md) for the channel-by-intent
view with links to every entry, and [corpus statistics](../registry/stats.json) for
counts by channel, intent, and status.

## Entry status

Each entry declares one of three maturity levels:

- `documented` — described with a threat model and a falsifiable success condition.
- `reproduced` — demonstrated at least once against a real target.
- `harness-supported` — bound to a runnable declarative test under `harness/tests/`.

## Adding a technique

Copy [`_template/technique.md`](_template/technique.md), fill in the front matter and
sections, and open a single-file pull request. An entry without a falsifiable
`success` field is not accepted. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Identifier scheme

Every technique carries three identifiers:

- **slug** — the human-readable filename, for example `C2-I3-smartfarm-note-override`.
- **registry_id** — a stable, never-reused, citable identifier, for example `AAT-0001`.
- **auto_generated_guid** — one per runnable test in `harness/tests/`.

Slugs may be renamed; the registry_id is permanent and is what the paper cites.
