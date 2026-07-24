"""Validator interface (Strategy). A validator inspects the kept instances of
a run directory and issues per-instance pass/fail verdicts; the runner then
discards failing instances. New validation stages = new Validator subclasses.
"""

from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import ClassVar, Optional

NON_INSTANCE_DIRS = {"shared", "qa_artifacts"}


@dataclass
class ValidationVerdict:
    instance_id: str
    passed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class ValidationContext:
    """Everything a validator may need about the run being validated."""

    run_dir: Path
    repo_key: str
    image: str
    workdir: str = "/testbed"
    settings: dict = field(default_factory=dict)

    @property
    def instances_dir(self) -> Path:
        return self.run_dir / "instances"

    def instance_dirs(self) -> list[Path]:
        return sorted(
            p
            for p in self.instances_dir.iterdir()
            if p.is_dir()
            and p.name not in NON_INSTANCE_DIRS
            and (p / "oracle.json").is_file()
        )

    def load_oracle(self, instance_dir: Path) -> Optional[dict]:
        try:
            return json.loads(
                (instance_dir / "oracle.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def from_run_dir(cls, run_dir: Path, settings: Optional[dict] = None) -> "ValidationContext":
        config_path = run_dir / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(
            run_dir=run_dir,
            repo_key=config["repo_key"],
            image=config["image"],
            workdir=config.get("workdir", "/testbed"),
            settings=settings or {},
        )


class Validator(ABC):
    """One validation stage. `validate` returns a verdict per instance; it must
    not move or delete anything — discarding is the runner's job."""

    name: ClassVar[str] = "abstract"

    def __init__(self, settings: Optional[dict] = None):
        self.settings = settings or {}

    @abstractmethod
    def validate(self, ctx: ValidationContext) -> list[ValidationVerdict]:
        ...

    def scope_key(self) -> str:
        """Path-safe sub-namespace identifying THIS run of the validator, so
        outputs from different agents/models never overwrite each other.
        Default: the validator name alone (single-scope validators). The
        solver-agent validator overrides this with "<agent>/<model>"."""
        return self.name

    def describe(self) -> dict:
        """Metadata identifying this run (agent, model, ...) for the report."""
        return {}


def safe_name(name: str) -> str:
    """Filesystem-safe token: replace slashes and whitespace with underscores
    (keeps hyphens/dots), mirroring RepoBehave's model-dir naming."""
    return re.sub(r"[/\s]+", "_", name.strip())


def write_eval_bundle(instance_dir: Path, oracle: dict, dest: Path) -> Path:
    """Stage a leak-free evaluation bundle for a solver (agent or LLM):
    question.json (oracle minus oracle_answer) plus files/ without parser
    scripts or pycache. Mirrors RepoBehave's make_qa_instances_eval. Returns
    the dest directory."""
    dest.mkdir(parents=True, exist_ok=True)
    question = {k: v for k, v in oracle.items() if k != "oracle_answer"}
    (dest / "question.json").write_text(
        json.dumps(question, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files_dir = instance_dir / "files"
    if files_dir.is_dir():
        for src in files_dir.rglob("*"):
            if not src.is_file():
                continue
            if src.name.startswith("parse") and src.suffix == ".py":
                continue
            if "__pycache__" in src.parts or src.suffix == ".pyc":
                continue
            out = dest / "files" / src.relative_to(files_dir)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
    return dest


def verdicts_to_dicts(verdicts: list[ValidationVerdict]) -> list[dict]:
    return [asdict(v) for v in verdicts]
