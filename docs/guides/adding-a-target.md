# Testing your own agent

The Workbench tests an authorized AI agent without repository code changes. Configure
what the agent perceives, how the input reaches it, and what observable response or
tool action proves a violation.

## Configure a target

1. Start `make workbench-api` and `make workbench-web` in separate terminals.
2. Open **Targets** and create a staging or production profile.
3. Choose the connector matching the real ingress: HTTP, TCP, MQTT, WebSocket, voice,
   optical HTTP, or an allowlisted device bridge.
4. Define the deterministic request template and response/action paths. Reference
   credentials by environment-variable name; never paste secret values into the UI.
5. Add response markers or forbidden tool names that mechanically prove a violation.
6. In **Workbench**, choose the input adapter, edit its decoded fields, preview the
   wire request, and send one controlled request.
7. Use **Campaigns** only after the single request is correct and batch execution is
   within the authorization scope. Review retained evidence in **History**.

Input adapters and connectors answer different questions:

```text
input adapter: what does the agent perceive?
connector:     how does the Workbench deliver it?
```

A `sensor-value` input can travel through MQTT, HTTP, TCP, or WebSocket. A
`voice-transcript` can use a voice service. Keep these choices independent unless the
target contract requires a particular combination.

## Optional LLM mapping

Use the input mapper only when a deterministic request template cannot express the
target contract. Mapper output is untrusted, bounded, validated, and retained.

Use the response mapper when stable `response_path` and `actions_path` values cannot
normalize the target output. The raw response remains authoritative evidence; mapper
output alone cannot confirm a violation.

## Safe verification

- Start with a staging or intentionally vulnerable lab target.
- Configure exact evidence rules before a production run.
- Keep production and hardware campaigns serialized.
- Treat `inconclusive` as “insufficient evidence,” never as proof that the agent is
  secure.
- Use the connector fixtures in
  [testing-workbench-connectors.md](testing-workbench-connectors.md) to validate a
  target profile shape without contacting a real deployment.
