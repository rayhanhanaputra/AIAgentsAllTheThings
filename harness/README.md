# Harness

The harness is the executable engine that runs a technique end-to-end against a
target agent and decides, mechanically, whether the attack succeeded.

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
attack-success breakdown. A live LLM target (`agribot-llm`) is provided for
demonstrations against a real model.

To point the harness at your own agent, write a Target adapter that drives it and
records its tool calls; every payload then runs against it unchanged. See
[docs/guides/adding-a-target.md](../docs/guides/adding-a-target.md).

## Design invariants

- **Simulator-first.** Execution runs in-process over the `direct` transport against a
  simulator or reference target. The `hardware: true` field is reserved for future
  hardware channels and never runs by default.
- **Mechanical oracle.** The primary verdict is a predicate over the action log, not
  an LLM judgment.
- **Benign baseline.** Every test declares a benign twin that must not trigger the
  unsafe action, yielding a false-positive measurement alongside attack success.

## Running

Install dependencies and run the offline, deterministic pipeline (in-process `direct`
transport, no broker required):

```bash
pip install -r requirements.txt        # or: pip install -e .  (adds the `aat` command)
python -m harness.cli list                                 # list registered plugins
python -m harness.cli run    C2-I3-smartfarm-note-override # verify the attack reproduces
python -m harness.cli demo   C2-I3-smartfarm-note-override # vulnerable vs hardened + report
python -m harness.cli ablate C2-I3-smartfarm-note-override # per-mitigation ASR breakdown
```

`demo` prints the attack-success rate for the vulnerable and hardened targets and the
mitigation delta, and writes an evidence report to `out/`.

The live MQTT version of the same scenario (real broker, real round trip, optional real
LLM target) is under [`sims/`](../sims/README.md).

To drive a real model instead of the deterministic reference agent, pass
`--target agribot-llm` (requires the anthropic SDK and an API key).
