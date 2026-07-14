"""Claude Code CLI backend (placeholder). Implement prepare/run_task
analogously to CursorBackend, following RepoBehave's
run_claude_code_eval_in_docker.sh (auth via ANTHROPIC_API_KEY, one
non-interactive `claude -p` session per prompt)."""

from __future__ import annotations

from pathlib import Path

from ..docker_env import Container
from .base import AgentBackend, AgentResult
from . import register


@register
class ClaudeCodeBackend(AgentBackend):
    name = "claude-code"

    def prepare(self, container: Container) -> None:
        raise NotImplementedError(
            "claude-code backend not implemented yet; use --agent cursor"
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
            "claude-code backend not implemented yet; use --agent cursor"
        )
