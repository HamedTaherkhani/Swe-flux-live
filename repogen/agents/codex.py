"""Codex CLI backend (placeholder). Implement prepare/run_task analogously to
CursorBackend: install the codex CLI into the container, then run one
non-interactive session per prompt."""

from __future__ import annotations

from pathlib import Path

from ..docker_env import Container
from .base import AgentBackend, AgentResult
from . import register


@register
class CodexBackend(AgentBackend):
    name = "codex"

    def prepare(self, container: Container) -> None:
        raise NotImplementedError(
            "codex backend not implemented yet; use --agent cursor"
        )

    def run_task(
        self,
        container: Container,
        prompt_container_path: str,
        workspace: str,
        host_log_dir: Path,
        tag: str,
        timeout_s: int,
    ) -> AgentResult:
        raise NotImplementedError(
            "codex backend not implemented yet; use --agent cursor"
        )
