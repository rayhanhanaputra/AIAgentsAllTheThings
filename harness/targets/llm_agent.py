"""Generic OpenAI-compatible LLM agent target — usable for ANY scenario.

Instead of a hand-written mock, this drives a real chat-completions endpoint (function
calling) against whatever scenario is under test. It reads the scenario's agent spec:

    agent_prompt     : the (naive, under-defended) system prompt
    agent_hardening  : safety instructions appended only when a mitigation is enabled
    agent_tools      : compact tool specs [{name, desc, params}] -> OpenAI functions
    perceive(body)   : optional; renders the channel message as the text the agent reads
                       (default: the JSON body)

By default the agent is naive (no guardrail) so an injection can succeed; pass any
mitigation to append the hardening prompt. The model's tool call is recorded verbatim
as an Action, so the scenario's own oracle judges it.

Config (env, first match wins):
  base URL: AAT_LLM_BASE_URL | OPENAI_BASE_URL | ANTHROPIC_BASE_URL
  api key:  AAT_LLM_API_KEY  | OPENAI_API_KEY  | ANTHROPIC_API_KEY
  model:    AAT_LLM_MODEL
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
_SCALARS = {"string": {"type": "string"}, "integer": {"type": "integer"},
            "number": {"type": "number"}, "boolean": {"type": "boolean"}}


def _tool_schema(tool: dict) -> dict:
    props, required = {}, []
    for name, spec in (tool.get("params") or {}).items():
        props[name] = {"type": "string", "enum": spec} if isinstance(spec, list) else _SCALARS.get(spec, {"type": "string"})
        required.append(name)
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("desc", ""),
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _extract_message(raw: str) -> dict:
    """Normalize a chat-completions response to an OpenAI `message` dict.

    Handles three shapes seen across proxies: a plain JSON object (optionally with a
    trailing `data: [DONE]`), a Server-Sent-Events stream (`data: {...}` lines), and a
    streamed sequence of delta chunks whose content and tool-call arguments are
    reassembled by index.
    """
    raw = raw.strip()
    decoder = json.JSONDecoder()

    # Case 1: a single JSON object, possibly with trailing bytes (e.g. "data: [DONE]").
    if raw[:1] == "{":
        try:
            obj, _ = decoder.raw_decode(raw)
            choice = (obj.get("choices") or [{}])[0]
            if choice.get("message"):
                return choice["message"]
        except json.JSONDecodeError:
            pass

    # Case 2/3: SSE or a chunked delta stream.
    content, slots, saw_chunk = "", {}, False
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        saw_chunk = True
        choice = (chunk.get("choices") or [{}])[0]
        if choice.get("message"):
            return choice["message"]
        delta = choice.get("delta") or {}
        content += delta.get("content") or ""
        for tc in delta.get("tool_calls") or []:
            slot = slots.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            slot["arguments"] += fn.get("arguments") or ""

    if saw_chunk:
        return {
            "content": content,
            "tool_calls": [{"function": {"name": s["name"], "arguments": s["arguments"]}}
                           for s in slots.values() if s["name"]],
        }

    # Fallback: first JSON object anywhere in the body.
    idx = raw.find("{")
    if idx != -1:
        try:
            obj, _ = decoder.raw_decode(raw[idx:])
            return (obj.get("choices") or [{}])[0].get("message", {}) or {}
        except json.JSONDecodeError:
            pass
    return {}


@register("target", "llm-agent")
class LLMAgent:
    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []
        self.scenario_obj = None  # injected by the engine
        self.base = _env("AAT_LLM_BASE_URL", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL",
                         default="https://api.openai.com").rstrip("/")
        self.key = _env("AAT_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
        self.model = os.getenv("AAT_LLM_MODEL", "gpt-4o-mini")
        if not self.key:
            raise RuntimeError(
                "llm-agent: no API key. Set AAT_LLM_API_KEY / OPENAI_API_KEY / "
                "ANTHROPIC_API_KEY, then retry."
            )

    def reset(self) -> None:
        self.actions = []

    def _chat(self, system: str, user: str, tools: list) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": 1024,
        }
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                     "User-Agent": _UA},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return _extract_message(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"llm-agent request failed: HTTP {exc.code} {exc.read()[:300].decode(errors='replace')}")
        except Exception as exc:
            raise RuntimeError(f"llm-agent request failed: {exc}")

    def handle(self, message: Message) -> None:
        sc = self.scenario_obj
        mid = message.msg_id
        if sc is None or not getattr(sc, "agent_tools", None):
            raise RuntimeError(
                f"llm-agent: scenario '{getattr(sc, 'name', '?')}' has no agent spec "
                f"(agent_prompt / agent_tools)."
            )
        perceive = getattr(sc, "perceive", None)
        user = perceive(message.body) if callable(perceive) else "Incoming input: " + json.dumps(message.body)
        system = sc.agent_prompt
        if self.mitigations:  # any mitigation enables model-side hardening
            system = system + " " + getattr(sc, "agent_hardening", "")
        tools = [_tool_schema(t) for t in sc.agent_tools]
        tool_names = {t["name"] for t in sc.agent_tools}

        msg = self._chat(system, user, tools)
        recorded = False
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            if fn.get("name") in tool_names:
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                self.actions.append(Action(fn["name"], args, mid, None, "llm tool call"))
                recorded = True
        if not recorded:
            self.actions.append(Action("noop", {}, mid, None, "llm took no action"))
