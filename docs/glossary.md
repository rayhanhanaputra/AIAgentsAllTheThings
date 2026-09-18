# Glossary

Canonical definitions used across the Web Workbench, knowledge base, CLI harness, and
simulators. Other documents reference this file rather than redefining terms.

- **Agent** — an LLM-driven system that autonomously observes inputs, reasons, and
  invokes tools or actuators, including physical ones.
- **Channel** — the medium through which the agent receives an input: an MQTT topic, a
  phone line, a microphone, a camera, a serial port, an RF interface, or a retrieved
  document.
- **Input adapter** — a Workbench encoder that turns user-supplied fields into the
  representation perceived by the target, such as JSON telemetry, a voice transcript,
  Morse timing, an image, or a BLE advertisement.
- **Connector** — the delivery mechanism between the Workbench and the target, such as
  HTTP, TCP, MQTT, WebSocket, a voice or optical service, or a guarded device bridge.
- **Target profile** — a saved, non-secret description of an authorized agent endpoint,
  its connector, request template, safety environment, and evidence rules.
- **Input mapper** — an optional OpenAI-compatible model that converts an encoded input
  into a target-specific request shape when a deterministic request template is not
  sufficient. Its output remains untrusted and is validated before delivery.
- **Workbench** — the single-run tool used to select an input adapter, inspect its
  encoded and wire representations, send it to a target, and capture the response.
- **Campaign** — the batch-testing tool that places multiple payloads into one channel
  template, sends each case, and retains each request, response, and verdict.
- **Evidence rule** — a deterministic response marker or forbidden tool name used to
  confirm a security violation. Without one, a captured response is inconclusive.
- **Signal-to-prompt injection** — an attack that uses a non-text channel to place
  attacker-controlled content into the agent's reasoning context. Also called
  cross-channel injection.
- **Trust boundary** — the line between data the agent should treat as untrusted
  observation and content it treats as trusted instruction or authoritative fact.
- **Privileged action** — a tool call or actuator command with real-world effect,
  especially one governed by a safety policy.
- **Oracle** — the mechanism that decides whether an attack succeeded, as a predicate
  over the target's action log.
- **Action log** — the structured record of every tool call and actuator command the
  instrumented target emits, with arguments and the id of the triggering input.
- **Benign baseline (benign twin)** — a legitimate input with the same surface
  features as an attack but no injected instruction, which must not trigger the unsafe
  action; used to measure false positives.
- **Attack Success Rate (ASR)** — the fraction of malicious runs the oracle scores as
  successful.
- **False-Positive Rate (FPR)** — the fraction of benign runs that nonetheless produce
  a policy-violating action.
- **Simulation environment** — the safe default target used to learn and preview the
  workflow without external delivery.
- **Production environment** — an explicitly configured, authorized real target.
  Every run requires acknowledgement; campaigns are forced to concurrency one.
