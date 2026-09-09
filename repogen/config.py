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


# Keys/values as they appear in the loaded .env file (normalized key -> value).
# Unlike os.environ this is never polluted by the parent process environment,
# so it represents explicit user configuration (see env_file_lookup).
ENV_FILE_VALUES: dict[str, str] = {}


def load_env_file(explicit_path: Optional[Path] = None) -> Optional[Path]:
    """Load KEY=VALUE pairs into os.environ (without overriding existing vars).

    Uses the explicit path if given, otherwise ONLY this project's own .env
    (<project root>/.env). Returns the file that was loaded, or None.
    """
    candidates = [explicit_path] if explicit_path else [PROJECT_ROOT / ".env"]
    for candidate in candidates:
        if candidate and candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key:
                    ENV_FILE_VALUES[_norm_key(key)] = value
                if key and key not in os.environ:
                    os.environ[key] = value
            return candidate
    return None


def env_file_lookup(*names: str) -> str:
    """Find the first matching key that was defined in the loaded .env FILE
    (ignoring inherited process environment). Matching is case- and
    hyphen/underscore-insensitive."""
    for name in names:
        value = ENV_FILE_VALUES.get(_norm_key(name))
        if value:
            return value
    return ""


# Canonical provider API-key env vars -> accepted aliases (matched
# case-insensitively and hyphen/underscore-insensitively). Lets a .env with
# names like `anthropic-api-key` or `gemini_key` satisfy the SDKs, which read
# the canonical uppercase names.
_PROVIDER_KEY_ALIASES = {
    "OPENAI_API_KEY": ["openai_api_key", "openai_key"],
    "ANTHROPIC_API_KEY": ["anthropic_api_key", "anthropic_key"],
    "GEMINI_API_KEY": ["gemini_api_key", "gemini_key", "google_api_key", "google_gemini_api_key"],
    "GOOGLE_API_KEY": ["google_api_key", "gemini_api_key", "gemini_key"],
    "FIREWORKS_API_KEY": ["fireworks_api_key", "fireworks_api_token", "fireworks_key"],
    "DEEPSEEK_API_KEY": ["deepseek_api_key", "deepseek_key"],
    "OPENROUTER_API_KEY": ["openrouter_api_key", "openrouter_key"],
    "CURSOR_API_KEY": ["cursor_api_key"],
    "MOONSHOT_API_KEY": ["moonshot_api_key", "kimi_api_key", "moonshot_key", "kimi_key"],
}


def _norm_key(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def hydrate_provider_env() -> list[str]:
    """Populate canonical provider API-key env vars from any alias present in the
    environment (e.g. `anthropic-api-key` -> `ANTHROPIC_API_KEY`). Existing
    canonical values are left untouched. Returns the canonical names that were
    set, for logging."""
    normalized = {
        _norm_key(k): v for k, v in os.environ.items() if v and v.strip()
    }
    filled: list[str] = []
    for canonical, aliases in _PROVIDER_KEY_ALIASES.items():
        if os.environ.get(canonical):
            continue
        for alias in [canonical, *aliases]:
            value = normalized.get(_norm_key(alias))
            if value:
                os.environ[canonical] = value
                filled.append(canonical)
                break
    return filled


def env_lookup(*names: str) -> str:
    """Find the first matching env var, trying exact, upper, and lower forms."""
    for name in names:
        for variant in (name, name.upper(), name.lower()):
            value = os.environ.get(variant)
            if value:
                return value
    return ""


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
    agent_timeout_s: int = 900
    # Concurrent generation containers. Each worker owns one container running
    # its own agent session and pytest harvests, so RAM scales with this.
    parallel: int = 1
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
