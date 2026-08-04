"""Validator registry (Factory) + the runner that applies validators in order
and discards failing instances. Adding a validation stage = subclass Validator,
decorate with @register, import the module here, and pass its name via
--validators."""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Optional, Type

from .base import (
    ValidationContext,
    ValidationVerdict,
    Validator,
    verdicts_to_dicts,
)

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
    discard: bool = True,
) -> dict:
    """Apply VALIDATION stages sequentially over the current instances/ set.

    Each run is namespaced by its scope (for the solver-agent validator:
    <agent>/<model>), so outputs and discards from different models never
    overwrite each other and validating with a new model ADDS to the record.
    When `discard` is on, instances a stage fails move to
    validation_excluded/<validator>/<scope>/ (so, run sequentially, an instance
    survives only if every model that validated it passed). Accumulates all
    runs across invocations in validation_report.json.

    Evaluation-only stages must not be passed here — use run_evaluators."""
    for validator in validators:
        if getattr(validator, "evaluation_only", False):
            raise ValueError(
                f"validator '{validator.name}' is evaluation-only; run it with "
                "run_evaluators (the `evaluate` command), not run_validators"
            )
    return _run_stage(
        ctx, validators, discard=discard,
        report_name="validation_report.json", label="validate",
    )


def run_evaluators(
    ctx: ValidationContext,
    evaluators: list[Validator],
) -> dict:
    """Apply EVALUATION stages (e.g. solver_llm) over the current instances/ set.

    Evaluation never discards: it only measures how a solver does and records
    per-instance answers, scores, and costs under evaluation/. Accumulates all
    runs across invocations in evaluation_report.json."""
    return _run_stage(
        ctx, evaluators, discard=False,
        report_name="evaluation_report.json", label="evaluate",
    )


def _run_stage(
    ctx: ValidationContext,
    validators: list[Validator],
    *,
    discard: bool,
    report_name: str,
    label: str,
) -> dict:
    report = _load_report(ctx, report_name)
    timestamp = _dt.datetime.now().isoformat(timespec="seconds")

    for validator in validators:
        scope = validator.scope_key()
        can_discard = discard and not getattr(validator, "evaluation_only", False)
        only = validator.settings.get("instance_ids")
        count = len(only) if only is not None else len(ctx.instance_dirs())
        print(f"[{label}] stage '{validator.name}' scope '{scope}' "
              f"on {count} instances")
        verdicts = validator.validate(ctx)
        failed = [v for v in verdicts if not v.passed]
        if can_discard:
            for verdict in failed:
                _discard(ctx, validator.name, scope, verdict.instance_id)
        run_entry = {
            "validator": validator.name,
            "scope": scope,
            "timestamp": timestamp,
            "discarded": can_discard,
            "total": len(verdicts),
            "passed": len(verdicts) - len(failed),
            "failed": len(failed),
            "verdicts": verdicts_to_dicts(verdicts),
        }
        run_entry.update(validator.describe())
        report["runs"].append(run_entry)

    report["run_dir"] = str(ctx.run_dir)
    report["remaining_instances"] = [p.name for p in ctx.instance_dirs()]
    report_path = ctx.run_dir / report_name
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return report


def _load_report(ctx: ValidationContext, report_name: str) -> dict:
    """Read an accumulating report, tolerating (and migrating) the old
    single-run 'stages' format so earlier runs are not lost."""
    path = ctx.run_dir / report_name
    if not path.is_file():
        return {"run_dir": str(ctx.run_dir), "runs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"run_dir": str(ctx.run_dir), "runs": []}
    if "runs" not in data:
        migrated = []
        for stage in data.get("stages", []):
            stage = dict(stage)
            stage.setdefault("scope", stage.get("validator", "unknown"))
            stage.setdefault("model", "unknown")
            migrated.append(stage)
        data = {"run_dir": data.get("run_dir", str(ctx.run_dir)), "runs": migrated}
    return data


def _discard(
    ctx: ValidationContext, stage_name: str, scope: str, instance_id: str
) -> None:
    source = ctx.instances_dir / instance_id
    if not source.is_dir():
        return
    # scope (e.g. "<agent>/<model>") is used as a subpath; its components are
    # already filesystem-safe (see the validator's scope_key).
    destination_root = ctx.run_dir / "validation_excluded" / stage_name / scope
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / instance_id
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(source), str(destination))


# Import concrete validators so they self-register.
from . import solver_agent  # noqa: E402,F401
from . import solver_llm  # noqa: E402,F401

def available_evaluators() -> list[str]:
    return sorted(n for n, cls in _REGISTRY.items() if getattr(cls, "evaluation_only", False))


def agent_validated_instances(run_dir: Path) -> Optional[set]:
    """Instance ids that at least one AGENT-validator run marked as passed
    (union across all non-evaluation validation runs in validation_report.json).

    Returns None if there is no validation report or no agent-validation runs
    (so callers can distinguish "nothing validated yet" from "validated, none
    passed" -> empty set)."""
    path = run_dir / "validation_report.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    eval_names = set(available_evaluators())
    passed: set = set()
    found_agent_run = False
    for run in data.get("runs", []):
        if run.get("validator") in eval_names:
            continue  # skip LLM-evaluation runs; only agent validation counts
        found_agent_run = True
        for verdict in run.get("verdicts", []):
            if verdict.get("passed") and verdict.get("instance_id"):
                passed.add(verdict["instance_id"])
    return passed if found_agent_run else None


def available_validation_stages() -> list[str]:
    return sorted(n for n, cls in _REGISTRY.items() if not getattr(cls, "evaluation_only", False))


__all__ = [
    "Validator",
    "ValidationContext",
    "ValidationVerdict",
    "register",
    "create_validator",
    "available_validators",
    "available_evaluators",
    "available_validation_stages",
    "agent_validated_instances",
    "run_validators",
    "run_evaluators",
]
