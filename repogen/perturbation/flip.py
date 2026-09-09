"""Flip stage: does the target model still answer the instance correctly?

A perturbation is *interesting* when the model answered the original instance
correctly but fails the perturbed one -- a pass -> fail flip. This module solves
one instance with the target model and scores it against the freshly harvested
oracle, reusing the evaluator's own bundle/inference/scoring path so a flip means
exactly what `repogen evaluate` would report.

INFRA GUARD: a provider refusal (quota exhausted, rate limit, expired auth) makes
the model produce no answer, which scores as "failed" and would look like a flip.
That would be a fabricated result, so refusals are detected and reported as
`infra_error` instead of as a verdict, and the caller must not count them.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..scoring import score_answer
from ..validation.base import write_eval_bundle

# Signatures of "the provider refused", not "the model was wrong".
_INFRA_PATTERNS = (
    "insufficient balance",
    "exceeded_current_quota",
    "quota",
    "rate_limit",
    "ratelimiterror",
    "429",
    "too many requests",
    "insufficient_quota",
    "authentication",
    "invalid api key",
    "permission denied",
    "does not exist or you do not have access",
    "model_not_found",
    "overloaded",
    "service unavailable",
    "502",
    "503",
    "504",
)


def looks_like_infra_error(message: str) -> bool:
    """Provider refusal: quota/auth/availability. Aborts the flip stage."""
    text = (message or "").lower()
    return any(p in text for p in _INFRA_PATTERNS)


def answer_never_obtained(reason: str) -> bool:
    """No answer was produced at all, for ANY reason.

    Broader than `looks_like_infra_error`: a malformed-request 400 is not a
    provider outage (so it should not abort the run), but it still means the
    model never answered -- so such a verdict is not evidence about whether the
    model can solve that instance, and must not seed a flip baseline.
    """
    text = (reason or "").lower()
    return (
        looks_like_infra_error(text)
        or "llm inference failed" in text
        or "no valid json" in text
        or "produced no answer" in text
    )


@dataclass
class FlipVerdict:
    instance_id: str
    passed: Optional[bool]          # None when the answer could not be obtained
    reason: str = ""
    infra_error: str = ""           # non-empty => provider refused; NOT a verdict
    cost_usd: Optional[float] = None

    @property
    def usable(self) -> bool:
        return self.passed is not None and not self.infra_error


class FlipChecker:
    """Solves one instance with the target model and scores it."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        repo_root: Path,
        out_root: Path,
        temperature: float = 0.0,
        reasoning_effort: str = "",
        max_read_lines: int = 250,
        repo_map_mode: str = "repomap",
        cheap_repomap_max_files: int = 2000,
        max_repair_rounds: int = 2,
        float_tol: float = 1e-6,
    ) -> None:
        self.provider = provider
        self.model = model
        self.repo_root = Path(repo_root)
        self.out_root = Path(out_root)
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.max_read_lines = max_read_lines
        self.repo_map_mode = repo_map_mode
        self.cheap_repomap_max_files = cheap_repomap_max_files
        self.max_repair_rounds = max_repair_rounds
        self.float_tol = float_tol

    def check(self, instance_dir: Path) -> FlipVerdict:
        from ..llm_eval import run_single_instance

        instance_id = instance_dir.name
        try:
            oracle = json.loads((instance_dir / "oracle.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return FlipVerdict(instance_id, None, f"unreadable oracle.json: {exc}")
        if "oracle_answer" not in oracle:
            return FlipVerdict(instance_id, None, "oracle.json has no oracle_answer")

        host_out = self.out_root / instance_id
        host_out.mkdir(parents=True, exist_ok=True)
        trace_lines: list[str] = []

        with tempfile.TemporaryDirectory(prefix="repogen_flip_") as tmp:
            bundle = write_eval_bundle(instance_dir, oracle, Path(tmp) / instance_id)
            try:
                parsed, debug = run_single_instance(
                    provider=self.provider,
                    model=self.model,
                    question_path=bundle / "question.json",
                    repo_root=self.repo_root,
                    max_read_lines=self.max_read_lines,
                    repo_map_mode=self.repo_map_mode,
                    cheap_repomap_max_files=self.cheap_repomap_max_files,
                    temperature=self.temperature,
                    reasoning_effort=self.reasoning_effort,
                    max_repair_rounds=self.max_repair_rounds,
                    trace=trace_lines.append,
                )
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {exc}"
                (host_out / "trace.log").write_text("\n".join(trace_lines), encoding="utf-8")
                if looks_like_infra_error(message):
                    # Never let a refusal masquerade as a model failure.
                    return FlipVerdict(instance_id, None, "", infra_error=message[:400])
                return FlipVerdict(instance_id, None, f"llm inference failed: {message[:300]}")

        (host_out / "answer.json").write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
        (host_out / "debug.json").write_text(
            json.dumps(debug, indent=2, default=str) + "\n", encoding="utf-8"
        )
        (host_out / "trace.log").write_text("\n".join(trace_lines), encoding="utf-8")

        cost = None
        if isinstance(debug, dict) and isinstance(debug.get("cost"), dict):
            cost = debug["cost"].get("cost_usd")

        correct, reason = score_answer(
            oracle["oracle_answer"], parsed, float_tol=self.float_tol
        )
        return FlipVerdict(instance_id, bool(correct), reason, cost_usd=cost)


def original_verdicts(run_dir: Path, provider: str, model: str) -> dict:
    """Pass/fail per instance from a source run's evaluation_report.json.

    Only verdicts from the SAME provider/model count -- a flip against a
    different model's baseline is meaningless. Verdicts whose failure reason is a
    provider refusal are skipped rather than trusted as failures.
    """
    report = run_dir / "evaluation_report.json"
    if not report.is_file():
        return {}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scope = f"{provider}/{model}"
    out: dict = {}
    for run in data.get("runs", []):
        if str(run.get("scope", "")).strip() != scope:
            continue
        for verdict in run.get("verdicts", []):
            reason = str(verdict.get("reason") or "")
            if not verdict.get("passed") and answer_never_obtained(reason):
                continue  # no answer was obtained; not evidence of anything
            out[verdict["instance_id"]] = bool(verdict.get("passed"))
    return out
