"""Generic HTTP target — point the harness at ANY running app over HTTP.

Sends the (perceived) channel content to a configured URL and records the app's
response, so the scenario's oracle can judge it. No code per app: it is configured
entirely by environment variables.

Config (env):
  AAT_AGENT_URL      (required) the running app's endpoint, e.g. http://localhost:8080/chat
  AAT_AGENT_METHOD   HTTP method (default POST)
  AAT_AGENT_FIELD    JSON field to carry the input (default "input")
  AAT_AGENT_HEADERS  extra headers as a JSON object (e.g. '{"Authorization":"Bearer x"}')
  AAT_AGENT_BODY     optional raw JSON body template with a literal {input} placeholder;
                     overrides AAT_AGENT_FIELD

The whole response body is recorded as an Action("response", {"text": ...}); if the
response is an OpenAI-style chat completion, its tool calls are also recorded so a
structured oracle can judge them. Pair with the `response_marker` oracle for apps that
just return text.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from harness.core.registry import register
from harness.core.types import Action, Message

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


@register("target", "http-agent")
class HttpAgent:
    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []
        self.scenario_obj = None  # injected by the engine
        self.url = os.getenv("AAT_AGENT_URL")
        self.method = os.getenv("AAT_AGENT_METHOD", "POST")
        self.field = os.getenv("AAT_AGENT_FIELD", "input")
        self.body_tmpl = os.getenv("AAT_AGENT_BODY")
        try:
            self.headers = json.loads(os.getenv("AAT_AGENT_HEADERS", "") or "{}")
        except json.JSONDecodeError:
            self.headers = {}
        if not self.url:
            raise RuntimeError("http-agent: set AAT_AGENT_URL to your running app's endpoint")

    def reset(self) -> None:
        self.actions = []

    def _input_text(self, body: dict) -> str:
        perceive = getattr(self.scenario_obj, "perceive", None)
        return perceive(body) if callable(perceive) else json.dumps(body)

    def handle(self, message: Message) -> None:
        text = self._input_text(message.body)
        if self.body_tmpl:
            data = self.body_tmpl.replace("{input}", json.dumps(text)[1:-1])
        else:
            data = json.dumps({self.field: text})
        headers = {"Content-Type": "application/json", "User-Agent": _UA}
        headers.update(self.headers)
        req = urllib.request.Request(self.url, data=data.encode(), headers=headers, method=self.method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode(errors="replace")
        except urllib.error.HTTPError as exc:
            raw = f"HTTP {exc.code}: " + exc.read()[:800].decode(errors="replace")
        except Exception as exc:
            raise RuntimeError(f"http-agent: cannot reach {self.url}: {exc}")

        self.actions.append(Action("response", {"text": raw[:4000]}, message.msg_id, None, "app response"))
        # If the app speaks OpenAI chat-completions, also record its tool calls.
        try:
            obj = json.loads(raw)
            msg = (obj.get("choices") or [{}])[0].get("message", {}) or {}
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                if fn.get("name"):
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    self.actions.append(Action(fn["name"], args, message.msg_id, None, "app tool call"))
        except (json.JSONDecodeError, AttributeError):
            pass
