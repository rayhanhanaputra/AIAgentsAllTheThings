# Offline CLI harness

The CLI harness is the deterministic companion to the Web Workbench. It reproduces a
knowledge-base technique end-to-end against a reference or instrumented target and
decides mechanically whether the attack succeeded. Use the Web Workbench for normal
interactive, batch, multi-channel, and real-target testing.

## Pipeline

```text
Scenario -> Payload -> Encoder -> Transport -> Target(agent) -> Oracle -> Report
```

## Plugin categories

Each category is a directory of plugins sharing a common (duck-typed) interface. New
channels are added by writing an encoder and a target; the rest of the pipeline
composes unchanged.

| Directory | Role |
| --- | --- |
| `scenarios/` | Deployment context, safety policy, protected assets |
| `payloads/` | Adversary intent, as a graded library (subtle to overt) |
| `encoders/` | Render a payload into a channel representation |
| `transports/` | Deliver the encoded payload to the target (`direct`, in-process) |
| `targets/` | Adapter to the agent under test; emits a structured action log |
| `oracles/` | Evaluate the action log against the scenario success condition |
| `reporters/` | Render the outcome and rates as a report |
| `tests/` | Declarative tests (YAML) bound to knowledge-base entries |

## Declarative tests

A test in `tests/<technique-slug>/*.yaml` names a scenario, payload, encoder, target,
oracle, the expected verdict, and the benign baseline. The `transport` block names the
realistic channel (a documented label such as `mqtt`, `voice`, or `gpio`) and is not
executed: automated runs deliver over the in-process `direct` transport. The
`oracle.name` is executed; `oracle.predicate` is a human-readable summary of it. Each
test carries a stable `auto_generated_guid` that the knowledge-base entry references
in its `tests` front matter, binding documentation to execution. `build_registry.py`
validates these fields.

## Reference targets

Each scenario's default target (`agribot-mock`, `callbot-mock`, `relaybot-mock`,
`scanbot-mock`, `resolverbot-mock`, `homebot-mock`, `controlbot-mock`,
`processbot-mock` — one per scenario) is an
explicit, deterministic model of a realistically-vulnerable agent: it has an
independent safety policy (a benign request is handled correctly) and one or more
mitigations that can be toggled on. `aat ablate <technique>` reports the per-mitigation
attack-success breakdown. The generic `llm-agent` target supports demonstrations
against an OpenAI-compatible model.

To point the harness at your own agent, write a Target adapter that drives it and
records its tool calls; every payload then runs against it unchanged. See
[docs/guides/adding-a-target.md](../docs/guides/adding-a-target.md).

## Design invariants

- **Deterministic by default.** CLI execution runs in-process over the `direct`
  transport against a simulator or reference target. Real connectors and guarded
  hardware delivery belong to the Web Workbench and never run implicitly.
- **Mechanical oracle.** The primary verdict is a predicate over the action log, not
  an LLM judgment.
- **Benign baseline.** Every test declares a benign twin that must not trigger the
  unsafe action, yielding a false-positive measurement alongside attack success.

## Running

Install dependencies and run the offline, deterministic pipeline (in-process `direct`
transport, no broker required):

```bash
python3 -m pip install --upgrade "pip>=23"
python3 -m pip install .               # installs the CLI and adds the `aat` command
python -m harness.cli list                                 # list registered plugins
python -m harness.cli run    C2-I3-smartfarm-note-override # verify the attack reproduces
python -m harness.cli demo   C2-I3-smartfarm-note-override # vulnerable vs hardened + report
python -m harness.cli ablate C2-I3-smartfarm-note-override # per-mitigation ASR breakdown
```

`demo` prints the attack-success rate for the vulnerable and hardened targets and the
mitigation delta, and writes an evidence report to `out/`.

The live MQTT version of the same scenario (real broker, real round trip, optional real
LLM target) is under [`sims/`](../sims/README.md).

To drive a real model instead of the deterministic reference agent, configure
`AAT_LLM_BASE_URL`, `AAT_LLM_API_KEY`, and `AAT_LLM_MODEL`, then pass
`--target llm-agent`.
