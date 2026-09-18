# Security and Responsible Use

AIAgentsAllTheThings is a defensive security research project. It exists to help
operators and researchers find and fix weaknesses in AI agents integrated with IoT
and cyber-physical systems, on systems they own or are explicitly authorized to test.

## Authorized use only

- Use this project only in a laboratory environment or against targets for which you
  have explicit written authorization.
- Production testing is supported by the Web Workbench, but only when the system owner
  has approved the exact targets, channels, payloads, time window, and expected impact.
- Do not use it against third-party systems, devices, or services you are not permitted
  to test.
- Manipulating sensors, actuators, or control systems without authorization may be
  illegal and may cause physical harm. You are responsible for your use.

## Real-target safeguards

- The Web Workbench defaults to the local simulator. Real HTTP(S), WebSocket,
  private-network TCP, private-network MQTT, and voice-service targets are explicit,
  opt-in profiles.
- Production execution requires acknowledgement for every run. Production campaigns
  run with concurrency one and retain the exact redacted request and captured evidence.
- Redirects are not followed. Requests, responses, timeouts, and TCP reads are bounded;
  link-local, multicast, unspecified, reserved, and cloud-metadata destinations are
  rejected. Public HTTP endpoints must use TLS.
- Credential values are read only from server environment variables. Target profiles
  store the variable name, never the credential value; secrets are not returned to the
  browser or written to history.
- Optional input and response mappers send canonical input or captured target output to
  the explicitly configured OpenAI-compatible service. Treat that service as a data
  processor for potentially sensitive assessment evidence. Raw target responses remain
  authoritative; response-mapper output is schema-validated, identified as normalized,
  never used by itself as deterministic evidence, and falls back to deterministic
  extraction when mapping fails.
- Voice audio is limited to 6 MiB, validated as Base64 with an allowlisted audio MIME
  type, and omitted from request previews and transcript metadata. Microphone capture
  stops automatically after 60 seconds.
- Realtime voice streams use bounded frame sizes, response-event counts, and total
  duration. Timeout, malformed media, and limit failures trigger the configured cancel
  event before the WebSocket is closed. Raw SIP signaling remains outside the process;
  connect through an authorized SIP gateway that exposes a secured media WebSocket.
- Optical uploads are limited to 8 MiB and 25 megapixels. The API decodes the image,
  verifies its real format against an allowlisted MIME type, rejects decompression
  bombs, and omits image bytes from previews and run history.
- BLE, NFC, and GPIO never receive direct unrestricted host access. A bridge profile
  pins one selected device and resource to explicit allowlists, caps active duration at
  30 seconds, requires acknowledgement for every run, forces campaign concurrency one,
  and calls a same-origin emergency-stop endpoint after success or failure.
- A response-only capture cannot prove an agent safe. Without explicit response-marker
  or forbidden-tool rules, the result is `inconclusive`.
- Raw SIP signaling and other unmodeled hardware/live-media
  connectors are not generic HTTP substitutes and are not implemented in the web
  workbench yet.

## Local evidence and retention

Workbench target profiles, request metadata, responses, events, analysis, and retained
audio are stored in the local SQLite database at `out/workbench.db` by default. The
database is not application-level encrypted and has no automatic retention window.
Protect it with host filesystem permissions and disk encryption, do not sync it to an
untrusted location, and delete it according to the assessment's evidence-retention
policy. The entire `out/` directory is ignored by Git.

## Responsible framing of the corpus

Every knowledge-base entry pairs the attack with detection and mitigation guidance and
is written for a defender testing their own agent. Contributions that are purely
offensive, that target a specific real deployment, or that include data obtained
without authorization are not accepted.

## Reporting a vulnerability

If you discover a vulnerability in this project's own code or infrastructure, please
report it privately rather than opening a public issue: open a private GitHub Security
Advisory on the repository (Security tab, "Report a vulnerability"). If that is
unavailable, contact a maintainer listed in the repository's git history. We will
acknowledge receipt and coordinate a fix and disclosure timeline.

If your research using this project uncovers a vulnerability in a third-party product,
follow that vendor's coordinated disclosure process. Do not publish deployment-specific
exploit details here.
