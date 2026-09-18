# Glossary

Canonical definitions used across the knowledge base, the harness, and the paper.
Other documents reference this file rather than redefining terms.

- **Agent** — an LLM-driven system that autonomously observes inputs, reasons, and
  invokes tools or actuators, including physical ones.
- **Channel** — the medium through which the agent receives an input: an MQTT topic, a
  phone line, a microphone, a camera, a serial port, an RF interface, or a retrieved
  document.
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
- **Simulator-first** — the principle that every scenario runs end-to-end against
  simulated devices by default, with real hardware strictly opt-in.
