"""Trace-grounded checkpoint ladder: intermediate-step evaluation.

`derive` turns each instance's harvested trace into checkpoints, a solver
answers them next to (inline) or after (probe) its final answer, and `score`
reports the first level at which the solver's account of the execution stops
matching the real one.

Artifacts:
  <run>/checkpoints/<instance>.json                      spec with ground truth
  <run>/evaluation/llm/<scope>/<instance>/checkpoints.json   solver's answers
  checkpoint_report.json                                 scored ladder
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..scoring import score_answer
from .derive import LEVELS, SCHEMA_VERSION, build_spec, plan_entries, public_view
from .score import ANSWER_LEVEL, LADDER, score_instance, summarise

MODES = ("off", "inline", "probe")
INLINE_SCOPE_SUFFIX = "__ckpt_inline"
NON_INSTANCE_DIRS = {"shared", "qa_artifacts"}

__all__ = [
    "ANSWER_LEVEL", "INLINE_SCOPE_SUFFIX", "LADDER", "LEVELS", "MODES",
    "build_report", "ensure_spec", "ensure_specs", "public_view",
    "score_instance", "spec_path", "write_report",
]


def spec_path(run_dir: Path, instance_id: str) -> Path:
    return run_dir / "checkpoints" / f"{instance_id}.json"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _workdir(run_dir: Path) -> str:
    config = _read_json(run_dir / "run_config.json")
    return (config or {}).get("workdir", "/testbed") if isinstance(config, dict) else "/testbed"


def ensure_spec(
    run_dir: Path,
    instance_dir: Path,
    *,
    refresh: bool = False,
    plan: Optional[dict] = None,
    workdir: Optional[str] = None,
) -> dict:
    """Load the instance's spec, deriving and caching it when absent."""
    path = spec_path(run_dir, instance_dir.name)
    if not refresh:
        cached = _read_json(path)
        if isinstance(cached, dict) and cached.get("schema_version") == SCHEMA_VERSION:
            return cached
    if plan is None:
        plan = plan_entries(run_dir)
    spec = build_spec(
        run_dir, instance_dir,
        workdir=workdir or _workdir(run_dir),
        plan_entry=plan.get(instance_dir.name),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return spec


def _instance_dirs(run_dir: Path) -> List[Path]:
    root = run_dir / "instances"
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and p.name not in NON_INSTANCE_DIRS and (p / "oracle.json").is_file()
    )


def ensure_specs(run_dir: Path, *, refresh: bool = False) -> Dict[str, dict]:
    plan = plan_entries(run_dir)
    workdir = _workdir(run_dir)
    return {
        instance_dir.name: ensure_spec(
            run_dir, instance_dir, refresh=refresh, plan=plan, workdir=workdir
        )
        for instance_dir in _instance_dirs(run_dir)
    }


def _scopes(run_dir: Path) -> List[str]:
    root = run_dir / "evaluation" / "llm"
    found = set()
    if root.is_dir():
        for path in root.glob("*/*/*/checkpoints.json"):
            found.add(f"{path.parents[2].name}/{path.parents[1].name}")
    return sorted(found)


def score_scope(run_dir: Path, scope: str, specs: Dict[str, dict], *, float_tol: float = 1e-6) -> List[dict]:
    rows: List[dict] = []
    scope_root = run_dir / "evaluation" / "llm" / scope
    for instance_id, spec in specs.items():
        if spec.get("status") != "ok":
            continue
        record = _read_json(scope_root / instance_id / "checkpoints.json")
        if not isinstance(record, dict):
            continue
        oracle = _read_json(run_dir / "instances" / instance_id / "oracle.json")
        answer = _read_json(scope_root / instance_id / "answer.json")
        final_correct = None
        if isinstance(oracle, dict) and "oracle_answer" in oracle and answer is not None:
            final_correct, _ = score_answer(oracle["oracle_answer"], answer, float_tol=float_tol)
        row = score_instance(
            spec, record.get("answer"), final_correct=final_correct, float_tol=float_tol
        )
        row["run_dir"] = str(run_dir)
        row["mode"] = record.get("mode", "")
        rows.append(row)
    return rows


def build_report(
    run_dirs: Iterable[Path],
    *,
    evaluation_scope: str = "",
    refresh: bool = False,
    float_tol: float = 1e-6,
) -> dict:
    run_dirs = list(run_dirs)
    derived = {"instances": 0, "available": 0, "unavailable": [], "levels": {l: 0 for l in LEVELS}}
    rows_by_scope: Dict[str, List[dict]] = {}
    for run_dir in run_dirs:
        specs = ensure_specs(run_dir, refresh=refresh)
        for instance_id, spec in specs.items():
            derived["instances"] += 1
            if spec.get("status") != "ok":
                derived["unavailable"].append(
                    {"run_dir": str(run_dir), "instance_id": instance_id,
                     "reason": spec.get("reason", "")}
                )
                continue
            derived["available"] += 1
            for level in {c["level"] for c in spec["checkpoints"]}:
                derived["levels"][level] += 1
        scopes = [evaluation_scope] if evaluation_scope else _scopes(run_dir)
        for scope in scopes:
            rows_by_scope.setdefault(scope, []).extend(
                score_scope(run_dir, scope, specs, float_tol=float_tol)
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "method": "trace_grounded_checkpoint_ladder",
        "ladder": list(LADDER),
        "run_dirs": [str(p) for p in run_dirs],
        "derived": derived,
        "scopes": {
            scope: {"summary": summarise(rows), "instances": rows}
            for scope, rows in sorted(rows_by_scope.items()) if rows
        },
    }


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
