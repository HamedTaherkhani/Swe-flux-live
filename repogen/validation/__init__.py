"""Validator registry (Factory) + the runner that applies validators in order
and discards failing instances. Adding a validation stage = subclass Validator,
decorate with @register, import the module here, and pass its name via
--validators."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional, Type

from .base import ValidationContext, ValidationVerdict, Validator, verdicts_to_dicts

_REGISTRY: dict[str, Type[Validator]] = {}


def register(cls: Type[Validator]) -> Type[Validator]:
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate validator name: {cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def create_validator(name: str, settings: Optional[dict] = None) -> Validator:
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown validator '{name}'; available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name](settings=settings)


def available_validators() -> list[str]:
    return sorted(_REGISTRY)


def run_validators(
    ctx: ValidationContext,
    validators: list[Validator],
    dry_run: bool = False,
) -> dict:
    """Apply validators sequentially. An instance discarded by one stage is not
    seen by later stages. Failing instances move to validation_excluded/<stage>/.
    Returns the report (also written to validation_report.json)."""
    stages = []
    for validator in validators:
        print(f"[validate] stage '{validator.name}' "
              f"on {len(ctx.instance_dirs())} instances")
        verdicts = validator.validate(ctx)
        failed = [v for v in verdicts if not v.passed]
        if not dry_run:
            for verdict in failed:
                _discard(ctx, validator.name, verdict.instance_id)
        stages.append(
            {
                "validator": validator.name,
                "total": len(verdicts),
                "passed": len(verdicts) - len(failed),
                "failed": len(failed),
                "verdicts": verdicts_to_dicts(verdicts),
            }
        )
    report = {
        "run_dir": str(ctx.run_dir),
        "dry_run": dry_run,
        "stages": stages,
        "remaining_instances": [p.name for p in ctx.instance_dirs()],
    }
    report_path = ctx.run_dir / "validation_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return report


def _discard(ctx: ValidationContext, stage_name: str, instance_id: str) -> None:
    source = ctx.instances_dir / instance_id
    if not source.is_dir():
        return
    destination_root = ctx.run_dir / "validation_excluded" / stage_name
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / instance_id
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(source), str(destination))


# Import concrete validators so they self-register.
from . import solver_agent  # noqa: E402,F401

__all__ = [
    "Validator",
    "ValidationContext",
    "ValidationVerdict",
    "register",
    "create_validator",
    "available_validators",
    "run_validators",
]
