"""Minimal registry for Workbench input encoders."""
from __future__ import annotations

from typing import Any, Callable

KINDS = ("encoder",)
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
    from harness import encoders  # noqa: F401
    _LOADED = True
