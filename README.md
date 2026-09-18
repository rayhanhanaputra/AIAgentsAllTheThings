# AIAgentsAllTheThings

**A security testing framework and knowledge base for AI agents integrated with IoT and cyber-physical systems.**

---

## Abstract

Large Language Model (LLM) agents are being deployed as autonomous controllers for
physical and semi-physical systems: call-center voice agents, smart-home
controllers, industrial and agricultural automation, building management, and
robotics. Unlike a chatbot, such an agent does not receive its inputs as clean text
in a message box. It ingests **signals** from the world: voice over a phone line,
telemetry from a sensor, the state of a switch, a tone, an image, a radio
advertisement. Each of these channels is an attack surface.

Existing AI red-teaming tools operate almost exclusively on the software text plane.
They test what a model *outputs* given adversarial *text* input. They do not model
the reality that a deployed agent's inputs arrive through physical and protocol-level
channels, and that any such channel can be used to smuggle adversarial instructions
or to manipulate the agent's decisions into unsafe physical actions.

**AIAgentsAllTheThings** addresses this gap. It is (1) a curated **knowledge base**
of attacks against AI agents wired into IoT and cyber-physical systems, and (2) a
**testing harness** that encodes each attack for the channel a deployed agent would
receive it on, delivers it to a target agent, and determines mechanically whether the
attack caused the agent to take a privileged or unsafe action. The harness runs
in-process for deterministic results; a live channel (MQTT) is demonstrated in the
simulators.

## Core thesis: signal-to-prompt injection

> Every signal an AI agent ingests is an injection surface.

We define **signal-to-prompt injection** (equivalently, *cross-channel injection*) as
an attack in which:

1. an attacker controls or influences a non-text channel the agent consumes
   (a sensor value, a switch state, an audio tone, an image, an RF frame);
2. the agent decodes or interprets that channel into its reasoning context; and
3. the decoded content causes the agent to cross a trust boundary — treating
   attacker-controlled data as trusted instruction, or being driven to an unsafe
   decision — resulting in a **privileged or physical action** the agent should not
   have taken.

The security-relevant event is never the decoding itself. Decoding a Morse blink or
reading a sensor value is benign. The event is the **privileged action** that
follows: a valve opened beyond a safety limit, a gate unlocked, a secret disclosed,
a control loop driven unstable. Every technique and every test in this project is
defined in terms of that action.

## Why current tooling is insufficient

| Tool | Focus | Gap for agent + IoT |
| --- | --- | --- |
| garak | LLM text-output vulnerability scanning | Model outputs, not agent actions; text only |
| Microsoft PyRIT | Generative-AI red-team orchestration | Strong engine; no IoT/physical transports or targets |
| promptfoo | Developer-facing eval and red-team configs | Text prompts; no cyber-physical channel model |
| OWASP / MITRE ATLAS | Threat catalogs and guidance | Reference frameworks, not runnable channel-level tests |

The common blind spot is the **channel**. None of these tools deliver a payload the
way a deployed agent receives it — over MQTT, over a phone line, over a relay's state
— or assert success in terms of a resulting physical action. That is the territory
this project owns.

## What this project provides

**1. Knowledge Base (`kb/`).** A browsable, contribution-friendly catalog of
techniques, encodings, and real-world scenarios, in the tradition of reference
corpora such as PayloadsAllTheThings. Entries are grouped into folders by the channel
that carries the injection (`kb/C1-sensor-value/` … `kb/C8-feedback-loop/`), each with
a per-folder Summary index. Each entry is a self-contained document with YAML front
matter and a threat model, the payload/encoding, the affected channel, a mandatory
falsifiable success condition, and defensive mitigations. Contributing an attack is a
single-file pull request: copy [`kb/_template/technique.md`](kb/_template/technique.md),
fill it in, and open it. An entry without a falsifiable `success` field is not
accepted. See [CONTRIBUTING.md](CONTRIBUTING.md).

**2. Testing Harness (`harness/`).** An executable pipeline that runs a technique
end-to-end against a target agent:

```text
Scenario  ->  Payload  ->  Encoder  ->  Transport  ->  Target(agent)  ->  Oracle  ->  Report
```

- **Scenario** — a real-world context and its safety policy and protected assets
  (irrigation controller, gate controller, call-center agent).
- **Payload** — the adversary intent (instruction override, tool/actuator abuse,
  data exfiltration, safety-limit violation, denial of service).
- **Encoder** — renders the payload into a channel representation (sensor value,
  structured data field, actuator state pattern, DTMF, Morse, QR, RF frame).
- **Transport** — delivers the encoded payload to the target. The harness executes
  in-process over the deterministic `direct` transport; the realistic channel a
  technique names (MQTT, voice, GPIO, ...) is a documented label, and the live
  demonstration over a real channel lives in the simulators under `sims/`.
- **Target** — an adapter to the agent under test, instrumented to emit a
  structured log of every tool call and actuator command.
- **Oracle** — evaluates the target's action log against the scenario's success
  condition. This is where "did the attack work?" is decided, crisply and
  falsifiably.
- **Report** — records the outcome, the evidence, a severity rating, and the
  mapping to standard threat frameworks.

The two halves share technique identifiers, so a knowledge-base entry maps directly
to a runnable test. Every technique carries three identifiers: a human-readable
**slug** (the filename), a stable, citable **registry_id** (`AAT-NNNN`), and one
**auto_generated_guid** per runnable test under `harness/tests/`. The machine-readable
index, the channel-by-intent matrix, and the corpus statistics under [`registry/`](registry/)
are generated from entry front matter by `tools/build_registry.py` and validated in CI.

## Quickstart

```bash
pip install --upgrade pip              # editable install needs pip >= 21.3
pip install -r requirements.txt        # or: pip install -e .
python -m harness.cli demo C2-I3-smartfarm-note-override
```

The demo prints the attack-success rate for the vulnerable and hardened agents and the
mitigation delta, and writes a Markdown evidence report to `out/`. Other commands:

```bash
python -m harness.cli list                                    # registered plugins
python -m harness.cli run    C3-I2-facility-morse-actuation
python -m harness.cli ablate C4-I4-callcenter-voice-override  # per-mitigation breakdown
pytest -q                                                     # deterministic test suite
```

Installing the package (`pip install -e .`) also provides an `aat` command equivalent
to `python -m harness.cli`. The live MQTT demonstration is under
[`sims/`](sims/README.md).

## Threat taxonomy

The full taxonomy and the Modality Injection Matrix are in
[`docs/taxonomy.md`](docs/taxonomy.md). In summary, techniques are organized by the
**channel** that carries the injection:

1. Sensor-value injection (spoofed, out-of-range, or overflowing telemetry)
2. Data-field injection (instructions smuggled into structured fields parsed as text)
3. Actuator / state-channel injection (binary toggles, Morse, timing patterns)
4. Acoustic / voice injection (adversarial audio, DTMF, ASR confusion)
5. Optical / visual injection (QR, barcodes, image steganography, text-in-image)
6. RF / protocol injection (BLE, Zigbee, LoRa, NFC)
7. Indirect / inter-agent injection (poisoned logs, transcripts, tool outputs, RAG)
8. Feedback-loop / control manipulation (replay, flooding, timing races)

Each technique is mapped to the OWASP Top 10 for LLM Applications (2025), the OWASP
Agentic AI threats (T1–T17), MITRE ATLAS, and — for the cyber-physical control channels
that ATLAS does not cover — MITRE ATT&CK for ICS. See [`docs/taxonomy.md`](docs/taxonomy.md).

## Design principles

- **Simulator-first.** Every scenario runs a full attack loop on a laptop with no
  hardware, against a deterministic reference target; the flagship also ships a device
  simulator (`sims/smartfarm`) for a live MQTT demonstration. Real hardware is out of
  scope for this release; when added it will attach behind the same transport interface.
- **Honest targets.** Each reference target is an explicit, deterministic model of a
  realistically-vulnerable agent with an independent safety policy (a benign request is
  handled correctly, so a bypass is not vacuous). Its mitigations are of two kinds, and
  `aat ablate` reports them separately: an out-of-band **policy gate**, which is
  sufficient *by construction* because it enforces the oracle's predicate in code, and
  **model-side** mitigations (input hardening), which the ablation shows are each only
  partial. Empirical robustness against a real model can be measured with the live LLM
  target (`agribot-llm`); no real-model numbers are shipped yet (a live-model
  evaluation is planned).
- **Falsifiable results.** Every scenario defines an explicit success condition and a
  benign baseline (a legitimate input that must *not* trigger the unsafe action), so
  the harness measures genuine robustness rather than a broken configuration.
- **Reproducible.** The offline pipeline is deterministic, dependencies are
  version-constrained, and a result can be re-run by a reviewer with one command.
- **Defender-oriented.** The intended user is an operator testing their own agent.
  Every technique documents detection and mitigation alongside the attack.

## Flagship demonstration

The first end-to-end scenario is a **smart-farm irrigation agent** subverted through
**sensor data-field injection** over MQTT: an attacker who can publish to a telemetry
topic causes the agent to open an irrigation valve far beyond its safety limit. It is
pure IoT, requires no telephony or audio stack, and runs entirely locally. The full
design, threat model, success oracle, metrics, and mitigations are in
[`docs/design/flagship-smart-farm-mqtt.md`](docs/design/flagship-smart-farm-mqtt.md).

This scenario is implemented end-to-end, and seven further techniques on different
channels reuse the same pipeline, adding only a new encoder and target (and an oracle
when the success condition is new) while the scenario runner, registry, and reporting
compose unchanged:

- `AAT-0002` (C4) — call-center voice / DTMF instruction override, exfiltrating a
  protected card number over an acoustic channel.
- `AAT-0003` (C3) — facility relay Morse and binary-toggle actuation, unlocking a gate
  from a read-only status-indicator channel.
- `AAT-0004` (C5) — logistics QR / OCR injection, triggering a shipment release or
  refund approval from an instruction hidden in a scanned code or label image.
- `AAT-0005` (C7) — support-desk inter-agent / RAG injection, laundering an
  authorization instruction through an upstream agent's note or a poisoned retrieved
  document into a refund or access grant.
- `AAT-0006` (C6) — smart-home RF injection, unlocking a door or disarming an alarm
  from an instruction in a BLE advertisement or NFC tag.
- `AAT-0007` (C8) — HVAC control-loop replay / flood, driving a heater past its safety
  cap by manipulating the reading stream (no instruction injected).
- `AAT-0008` (C1) — industrial tank sensor-value spoof, driving an inlet valve past its
  fill cap with an out-of-range or plausible-but-false level reading.

All eight taxonomy channels (C1–C8) expressing the same attack shape against one oracle
and one reporting path demonstrates that signal-to-prompt injection is a single
phenomenon the pipeline handles uniformly across channels.

All eight scenarios run offline and deterministically. Against each vulnerable
reference target the attack-success rate is 1.0 and drops to 0.0 once the policy gate
is enabled, with no false positives on the benign baselines; `aat ablate` shows the
model-side mitigations are each only partial. These are **reference-model** results:
the gate result holds by construction, and the mocks are explicit models of a
vulnerable agent, so they evidence the pipeline's generality rather than a real agent's
robustness. Real-model evidence via `agribot-llm` is planned, not yet shipped.

## Repository structure

```text
AIAgentsAllTheThings/
├── README.md
├── CONTRIBUTING.md                     # single-file KB PR flow; sanitization rules
├── SECURITY.md                         # responsible-use, scope controls, disclosure
├── LICENSE-CODE                        # Apache-2.0  -> harness/, sims/, tools/
├── LICENSE-DOCS                        # CC BY 4.0   -> kb/, docs/, registry/
├── docs/
│   ├── taxonomy.md                     # axes + illustrative Modality Injection Matrix
│   ├── glossary.md                     # canonical definitions
│   ├── style.md                        # entry style guide
│   └── design/
│       └── flagship-smart-farm-mqtt.md # extended design for the flagship scenario
├── kb/                                 # knowledge base — folder per channel
│   ├── README.md                       # channel index
│   ├── _template/technique.md          # copy-to-start template
│   ├── C1-sensor-value/ … C8-feedback-loop/
│   └── C2-data-field/C2-I3-smartfarm-note-override.md   # canonical flagship entry
├── harness/                            # testing engine and plugins
│   ├── scenarios/ payloads/ encoders/ transports/ targets/ oracles/ reporters/
│   └── tests/                          # declarative tests bound to KB entries by guid
├── sims/                               # simulated devices and target agents
├── registry/                           # GENERATED index: index.yaml/csv, matrix.md, stats.json
├── mappings/                           # controlled vocabularies (OWASP, ATLAS, ATT&CK-ICS, tags)
├── tools/build_registry.py             # builds and validates registry/ from front matter
└── .github/                            # issue/PR templates and CI (lint + validate + registry)
```

## Responsible use

This project exists to help operators and researchers find and fix weaknesses in AI
agents **that they own or are explicitly authorized to test**. It is not to be used
against systems without authorization.

- Use only in a laboratory environment or against targets you have written permission
  to test.
- All current execution drives simulated devices only. Real-hardware transports are
  not part of this release.
- Every knowledge-base entry pairs the attack with detection and mitigation guidance,
  and is framed for a defender testing their own system.

Details of the disclosure policy are in `SECURITY.md`.

## Status

Working preview (v0.1). The harness runs eight techniques end-to-end across all eight
taxonomy channels (C1–C8), each with a deterministic test suite. The smart-farm
scenario (C2) also ships a device simulator for a live MQTT demonstration. To test your
own agent, write a Target adapter — see
[docs/guides/adding-a-target.md](docs/guides/adding-a-target.md). Further channels, a
live-LLM evaluation, and an academic write-up are planned.

## Related work

garak; Microsoft PyRIT; promptfoo; Giskard; OWASP Top 10 for LLM Applications; OWASP
Agentic AI threats and mitigations; MITRE ATLAS. This project is complementary: it
contributes the cyber-physical channel model, the channel encoders and instrumented
targets, and the corresponding corpus, and can interoperate with existing
orchestration engines rather than replacing them.

## Authorship

Contributors are recorded through git commit history. Before the first public release,
set the security contact in `SECURITY.md`.

## License

Dual-licensed:

- **Code** (`harness/`, `sims/`, `tools/`) under Apache-2.0 — see [`LICENSE-CODE`](LICENSE-CODE).
- **Knowledge base and documentation** (`kb/`, `docs/`, and the generated `registry/`)
  under CC BY 4.0 — see [`LICENSE-DOCS`](LICENSE-DOCS).

## Citation

A `CITATION.cff` with named authors can be added at paper submission or first release.
Until then, attribution is through the git commit history.
