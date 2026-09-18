"""Generic TCP target — point the harness at a raw socket service (nc-style).

Opens a TCP connection to a configured host:port, sends the (perceived) channel content
as one JSON line, reads the response, and records it for the oracle. For line-oriented
agent services that are not HTTP.

Config (env):
  AAT_AGENT_HOST     (required) host of the running service
  AAT_AGENT_PORT     (required) port
  AAT_AGENT_FIELD    JSON field to carry the input (default "input")
  AAT_AGENT_RAW      if set (any value), send the raw input text + newline instead of JSON
  AAT_AGENT_TIMEOUT  socket timeout seconds (default 30)
"""
from __future__ import annotations

import json
import os
import socket

from harness.core.registry import register
from harness.core.types import Action, Message


@register("target", "tcp-agent")
class TcpAgent:
    def __init__(self, policy: dict, mitigations=frozenset()):
        self.policy = policy
        self.mitigations = frozenset(mitigations)
        self.actions: list[Action] = []
        self.scenario_obj = None  # injected by the engine
        self.host = os.getenv("AAT_AGENT_HOST")
        self.port = int(os.getenv("AAT_AGENT_PORT", "0") or 0)
        self.field = os.getenv("AAT_AGENT_FIELD", "input")
        self.raw = bool(os.getenv("AAT_AGENT_RAW"))
        self.timeout = float(os.getenv("AAT_AGENT_TIMEOUT", "30"))
        if not (self.host and self.port):
            raise RuntimeError("tcp-agent: set AAT_AGENT_HOST and AAT_AGENT_PORT")

    def reset(self) -> None:
        self.actions = []

    def _input_text(self, body: dict) -> str:
        perceive = getattr(self.scenario_obj, "perceive", None)
        return perceive(body) if callable(perceive) else json.dumps(body)

    def handle(self, message: Message) -> None:
        text = self._input_text(message.body)
        line = (text if self.raw else json.dumps({self.field: text})) + "\n"
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(line.encode())
                sock.settimeout(self.timeout)
                chunks = []
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if sum(len(c) for c in chunks) > 65536:
                            break
                except socket.timeout:
                    pass
        except OSError as exc:
            raise RuntimeError(f"tcp-agent: cannot reach {self.host}:{self.port}: {exc}")
        raw = b"".join(chunks).decode(errors="replace")
        self.actions.append(Action("response", {"text": raw[:4000]}, message.msg_id, None, "app response"))
