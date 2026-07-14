"""Run configuration and repository registry."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = Path(__file__).resolve().parent
PAYLOAD_DIR = PACKAGE_ROOT / "payload"
PROMPTS_DIR = PACKAGE_ROOT / "prompts"

ALL_CATEGORIES = [
    "S1_IntraProceduralCFG",
    "S2_Loops",
    "S3_ProgramState",
    "S4_DataFlow",
    "S5_Exceptions",
    "S6_InterProceduralCFG",
    "M1_IntraProceduralCFG",
    "M2_Loops",
    "M3_ProgramState",
    "M4_DataFlow",
    "M5_Exceptions",
    "M6_InterProceduralCFG",
    "M7_Invariants",
]


def load_repositories(repos_file: Path) -> dict[str, str]:
    with repos_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return re.sub(r"_+", "_", slug)


def default_qa_dir_name(repo_key: str) -> str:
    slug = sanitize_slug(repo_key)
    return slug if slug.endswith("_qa") else f"{slug}_qa"


@dataclass
class RunConfig:
    repo_key: str
    image: str
    agent_name: str
    model: str
    num_instances: int = 40
    categories: list[str] = field(default_factory=lambda: list(ALL_CATEGORIES))
    output_root: Path = PROJECT_ROOT / "out"
    workdir: str = "/testbed"
    qa_dir_name: str = ""
    seed: int = 7
    agent_timeout_s: int = 2400
    max_targets_per_module: int = 3
    plan_only: bool = False
    keep_container: bool = False
    targets_json: Optional[Path] = None
    agent_settings: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.qa_dir_name:
            self.qa_dir_name = default_qa_dir_name(self.repo_key)
        unknown = [c for c in self.categories if c not in ALL_CATEGORIES]
        if unknown:
            raise ValueError(f"Unknown categories: {unknown}")

    @property
    def container_qa_dir(self) -> str:
        return f"{self.workdir}/{self.qa_dir_name}"

    def run_dir(self, timestamp: str) -> Path:
        return self.output_root / self.repo_key / f"run_{timestamp}"

    @staticmethod
    def env_api_key(name: str) -> str:
        return os.environ.get(name, "")
