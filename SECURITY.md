# Security and Responsible Use

AIAgentsAllTheThings is a defensive security research project. It exists to help
operators and researchers find and fix weaknesses in AI agents integrated with IoT
and cyber-physical systems, on systems they own or are explicitly authorized to test.

## Authorized use only

- Use this project only in a laboratory environment or against targets for which you
  have explicit written authorization.
- Do not use it against production systems, third-party systems, or any device or
  service you are not permitted to test.
- Manipulating sensors, actuators, or control systems without authorization may be
  illegal and may cause physical harm. You are responsible for your use.

## Simulator-first

- All current execution drives the simulated devices under `sims/` and the in-process
  reference targets. A full attack loop runs locally without any physical hardware.
- Real-hardware transports are not implemented in this release. The `hardware: true`
  field is reserved in the declarative test schema for future hardware channels; when
  such transports are added they will be opt-in, will require an explicit authorized
  scope, and will never run by default.

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
