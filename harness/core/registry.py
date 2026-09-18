"""A minimal plugin registry.

Each plugin category is a namespace of named plugins. Plugins register themselves
at import time with the `register` decorator; `load_all` imports every plugin
package so the registries are populated before use.
"""
from __future__ import annotations

from typing import Any, Callable

KINDS = ("scenario", "payload", "encoder", "transport", "target", "oracle", "reporter")
_REGISTRIES: dict[str, dict[str, Any]] = {k: {} for k in KINDS}
_LOADED = False


def register(kind: str, name: str) -> Callable[[Any], Any]:
    if kind not in _REGISTRIES:
        raise ValueError(f"unknown plugin kind: {kind}")

    def decorator(obj: Any) -> Any:
        _REGISTRIES[kind][name] = obj
        return obj

    return decorator


def get(kind: str, name: str) -> Any:
    load_all()
    try:
        return _REGISTRIES[kind][name]
    except KeyError:
        raise KeyError(
            f"no {kind} named '{name}'. Available: {sorted(_REGISTRIES[kind])}"
        ) from None


def available(kind: str) -> list[str]:
    load_all()
    return sorted(_REGISTRIES[kind])


def load_all() -> None:
    global _LOADED
    if _LOADED:
        return
    # Import order does not matter; each package registers its plugins on import.
    from harness import (  # noqa: F401
        scenarios,
        payloads,
        encoders,
        transports,
        targets,
        oracles,
        reporters,
    )
    _LOADED = True
