"""Agent backend interface (Strategy). A backend knows how to install its CLI
into the benchmark container and how to run one prompt as one isolated session.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Optional

from ..docker_env import Container


@dataclass
class AgentResult:
    ok: bool
    exit_code: int
    log_path: Optional[Path] = None
    traj_path: Optional[Path] = None
    note: str = ""


class AgentBackend(ABC):
    """One instance == one fresh, stateless agent session inside the container."""

    name: ClassVar[str] = "abstract"

    def __init__(self, model: str, settings: Optional[dict] = None):
        self.model = model
        self.settings = settings or {}

    @abstractmethod
    def prepare(self, container: Container) -> None:
        """Install/authenticate the agent CLI inside the container. Called once
        per container, before any run_task call."""

    @abstractmethod
    def run_task(
        self,
        container: Container,
        prompt_container_path: str,
        workspace: str,
        host_log_dir: Path,
        tag: str,
        timeout_s: int,
    ) -> AgentResult:
        """Run one prompt (already staged at prompt_container_path) as a fresh
        session; persist logs/trajectory under host_log_dir using tag."""


def ndjson_to_json(src: Path, dst: Path) -> None:
    """Convert an agent's NDJSON event stream into {"events": [...]}; lines that
    are not JSON are kept as raw_line events."""
    events = []
    with src.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"type": "raw_line", "text": line})
    with dst.open("w", encoding="utf-8") as f:
        json.dump({"events": events}, f, indent=2, sort_keys=True)
        f.write("\n")
