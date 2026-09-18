# Testing your own agent: writing a Target adapter

The harness ships with deterministic reference agents, but its purpose is to test
*your* agent — a chatbot, a voice assistant, a Home Assistant automation, an
LLM-driven controller. You do that by writing one small **Target adapter**: a class
that receives the encoded attack, drives your agent with it, and records what
privileged actions your agent took. Every existing payload then runs against your
agent unchanged, and the scenario's oracle decides whether an attack succeeded.

## The Target interface

A target is a class with three things:

```python
from harness.core.registry import register
from harness.core.types import Action, Message


@register("target", "my-agent")           # the name you pass to --target
class MyAgent:
    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy               # the scenario's safety policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []    # the action log the oracle reads

    def reset(self) -> None:
        self.actions = []                  # called before each delivery

    def handle(self, message: Message) -> None:
        ...                                # drive your agent; append to self.actions
```

The three data types involved:

- `Message(msg_id, topic, body)` — the encoded attack. `body` is a dict holding the
  channel content (for the smart-farm scenario, `{"moisture": 12, "note": "..."}`).
- `Action(tool, args, trigger_msg_id, observed_moisture=None, note="")` — one entry in
  the action log. Record every tool call or actuator command your agent makes, with
  `tool` set to the action name and `args` to its arguments.
- The **oracle** reads `self.actions` and decides success. It looks for specific tool
  names (for example `set_valve`, `disclose`, `set_gate`, `release_shipment`), so map
  your agent's actions onto the scenario's names in the adapter (see below).

## Worked example: an HTTP agent

Suppose your agent is a service that accepts a JSON reading and returns the tool calls
it decided to make. The adapter turns the channel message into your agent's input,
calls it, and records the tool calls:

```python
import json
import os
import urllib.request

from harness.core.registry import register
from harness.core.types import Action, Message


@register("target", "my-http-agent")
class MyHttpAgent:
    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []
        self.url = os.getenv("MY_AGENT_URL", "http://localhost:8000/act")

    def reset(self) -> None:
        self.actions = []

    def handle(self, message: Message) -> None:
        # 1. turn the channel message into whatever your agent ingests
        data = json.dumps(message.body).encode()
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )
        # 2. drive your agent
        resp = json.load(urllib.request.urlopen(req, timeout=30))
        # 3. record the privileged actions your agent took, mapped to the scenario's names
        for call in resp.get("tool_calls", []):
            self.actions.append(
                Action(call["name"], call.get("args", {}), message.msg_id, None, "agent tool call")
            )
        if not self.actions:
            self.actions.append(Action("noop", {}, message.msg_id, None, "no action"))
```

For a Python agent framework (LangChain, LangGraph, a custom loop), skip the HTTP call:
import your agent, invoke it with `message.body`, and capture its tool calls through a
callback or instrumentation, appending each to `self.actions`.

## Mapping your agent's actions to the oracle

The oracle judges by tool name. If your agent calls a valve tool named
`irrigation.open(minutes=...)` but the `valve_policy` oracle looks for
`set_valve(duration_minutes=...)`, translate it in the adapter:

```python
if call["name"] == "irrigation.open":
    self.actions.append(Action(
        "set_valve",
        {"zone": call["args"]["zone"], "state": "open",
         "duration_minutes": call["args"]["minutes"]},
        message.msg_id, observed_moisture=message.body.get("moisture"),
    ))
```

Alternatively, write a small oracle for your agent's own action vocabulary — see
`harness/oracles/` for short examples (one per scenario).

## Running the payloads against your agent

Register the adapter (import it once so `@register` runs), then point any technique at
it:

```bash
python -m harness.cli run  C2-I3-smartfarm-note-override --target my-http-agent
python -m harness.cli demo C2-I3-smartfarm-note-override --target my-http-agent
```

Every payload in that technique is delivered to your agent, and the oracle reports the
attack-success rate and false-positive rate. Use `aat ablate` to see how each
mitigation your agent implements changes the outcome.

## Testing your own domain

If your agent is nothing like the shipped scenarios, add a scenario and payload library
for it (see `harness/scenarios/` and `harness/payloads/` for the pattern), plus an
oracle that encodes your safety policy. The pipeline, runner, registry, and reporting
are reused unchanged. See [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Notes

- Set a `scenario = "<scenario-name>"` class attribute so `aat` can reject a mismatched
  `--target` (for example, using a smart-farm target on a voice technique). A target
  without it opts out of that safety check.
- `observed_moisture` on `Action` is optional scenario context; leave it `None` unless
  the oracle needs it.
- Make `handle` tolerant of malformed input (coerce fields, reject non-finite numbers,
  catch exceptions) so a single bad message never crashes a long run.
- Live agents are nondeterministic; repeat runs and report variance rather than a
  single number.
