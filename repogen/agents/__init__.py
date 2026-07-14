"""Backend registry (Factory). Adding a backend = subclass AgentBackend,
decorate with @register, import the module here."""

from __future__ import annotations

from typing import Optional, Type

from .base import AgentBackend, AgentResult

_REGISTRY: dict[str, Type[AgentBackend]] = {}


def register(cls: Type[AgentBackend]) -> Type[AgentBackend]:
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate agent backend name: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def create_backend(name: str, model: str, settings: Optional[dict] = None) -> AgentBackend:
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown agent backend '{name}'; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](model=model, settings=settings)


def available_backends() -> list[str]:
    return sorted(_REGISTRY)


# Import concrete backends so they self-register.
from . import cursor  # noqa: E402,F401
from . import codex  # noqa: E402,F401
from . import claude_code  # noqa: E402,F401

__all__ = [
    "AgentBackend",
    "AgentResult",
    "register",
    "create_backend",
    "available_backends",
]
