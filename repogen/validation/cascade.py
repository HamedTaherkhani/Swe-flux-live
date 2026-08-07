"""Difficulty cascade: an ordered ladder of solver agents (weakest model first)
that both validates instances and assigns difficulty labels.

Tier 1 runs on every kept instance; instances it solves (ALL rollouts must
match the oracle) are accepted with tier 1's label (e.g. "easy") and leave the
cascade. The instances it fails escalate to tier 2, and so on. An instance's
difficulty is the label of the FIRST tier that solves it. Instances no tier
solves are rejected — with discarding on they move to
validation_excluded/cascade/failed_all_tiers/.

A tier with a PARTIAL label ("easy/medium=agent:model") adds a middle band:
instances where some but not all rollouts pass are ACCEPTED with the partial
label and leave the cascade (e.g. haiku 1-2/3 -> "medium"). A partial pass is
already evidence the oracle is reachable, and the mixed outcome is itself the
difficulty signal, so these need no confirmation from a stronger tier. Only
zero-pass instances escalate (e.g. haiku 0/3 -> fable; 3/3 there -> "hard").

Each tier is recorded as a normal solver_agent run in validation_report.json
(namespaced by <agent>/<model> as usual), so cascade passes count as agent
validation everywhere else (e.g. `repogen evaluate`'s default gating). The
cascade-level outcome — tiers, per-instance difficulty, rejections — is written
to difficulty_report.json, and each accepted instance gets a difficulty.json
next to its oracle.json.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from typing import Optional

from . import _discard, run_validators
from .base import ValidationContext, ValidationVerdict
from .solver_agent import SolverAgentValidator


@dataclass
class CascadeTier:
    label: str            # label when ALL rollouts pass, e.g. "easy"
    agent: str            # backend name, e.g. "claude-code"
    model: str            # model id for the backend
    partial_label: str = ""  # label when SOME (not all, not zero) rollouts pass

    @classmethod
    def parse(cls, spec: str) -> "CascadeTier":
        """Parse a CLI tier spec: LABEL[/PARTIAL_LABEL]=AGENT:MODEL.
        e.g. easy/medium=claude-code:claude-haiku-4-5-20251001 labels all-pass
        instances "easy", mixed-rollout instances "medium", and escalates only
        zero-pass instances. Without /PARTIAL_LABEL any failure escalates."""
        label, sep, rest = spec.partition("=")
        agent, sep2, model = rest.partition(":")
        if not sep or not sep2 or not label.strip() or not agent.strip() or not model.strip():
            raise ValueError(
                f"bad tier spec '{spec}' (expected LABEL[/PARTIAL]=AGENT:MODEL, "
                "e.g. easy/medium=claude-code:claude-haiku-4-5-20251001)"
            )
        label = label.strip()
        partial = ""
        if "/" in label:
            label, _, partial = label.partition("/")
            if not label.strip() or not partial.strip():
                raise ValueError(f"bad tier label '{spec}': use LABEL/PARTIAL_LABEL")
        return cls(
            label=label.strip(), agent=agent.strip(), model=model.strip(),
            partial_label=partial.strip(),
        )


def run_cascade(
    ctx: ValidationContext,
    tiers: list[CascadeTier],
    *,
    rollouts: int = 1,
    timeout_s: int = 900,
    float_tol: float = 1e-6,
    effort: str = "",
    parallel: int = 2,
    discard: bool = True,
    only_instance_ids: Optional[list[str]] = None,
) -> dict:
    if not tiers:
        raise ValueError("cascade needs at least one tier")
    labels = [t.label for t in tiers] + [t.partial_label for t in tiers if t.partial_label]
    if len(set(labels)) != len(labels):
        raise ValueError(f"duplicate tier labels: {labels}")

    remaining = [p.name for p in ctx.instance_dirs()]
    if only_instance_ids is not None:
        wanted = set(only_instance_ids)
        missing = wanted - set(remaining)
        if missing:
            raise ValueError(f"unknown/absent instance ids: {sorted(missing)}")
        remaining = [i for i in remaining if i in wanted]
    scope = set(remaining)  # labels outside this scope are preserved on merge
    # Clean slate: labels from a previous cascade run must not survive if this
    # run rejects (or relabels) the instance.
    for instance_id in remaining:
        (ctx.instances_dir / instance_id / "difficulty.json").unlink(missing_ok=True)
    assignments: dict[str, dict] = {}
    tier_summaries: list[dict] = []
    timestamp = _dt.datetime.now().isoformat(timespec="seconds")

    for index, tier in enumerate(tiers, start=1):
        if not remaining:
            print(f"[cascade] tier {index} '{tier.label}': nothing left to escalate")
            tier_summaries.append(_tier_summary(tier, index, [], []))
            continue
        print(
            f"[cascade] tier {index}/{len(tiers)} '{tier.label}' "
            f"({tier.agent} / {tier.model}) on {len(remaining)} instance(s), "
            f"{rollouts} rollout(s) each"
        )
        validator = SolverAgentValidator(settings={
            "agent": tier.agent,
            "model": tier.model,
            "timeout_s": timeout_s,
            "float_tol": float_tol,
            "rollouts": rollouts,
            "effort": effort,
            "parallel": parallel,
            "instance_ids": list(remaining),
            # With a partial label the tier needs the three-way outcome
            # (all/mixed/zero), so the solver counts passes instead of
            # failing fast.
            "count_passes": bool(tier.partial_label),
        })
        # Record the tier as a normal validation run; the cascade owns
        # discarding, so the per-tier run never prunes.
        report = run_validators(ctx, [validator], discard=False)
        verdicts = report["runs"][-1]["verdicts"]
        passed = [v["instance_id"] for v in verdicts if v["passed"]]
        partial = []
        if tier.partial_label:
            partial = [
                v["instance_id"] for v in verdicts
                if not v["passed"]
                and v.get("details", {}).get("pass_count", 0) > 0
            ]
        failed = [
            v["instance_id"] for v in verdicts
            if not v["passed"] and v["instance_id"] not in partial
        ]

        # Infra-failure guard. A rollout the provider refused (usage limit,
        # rate limit, expired auth) says NOTHING about the instance, so a
        # verdict resting on one is not evidence of failure — discarding over
        # it destroys good instances. Abort as soon as any failing instance
        # has such a rollout, so the user can fix the cause and re-run; prior
        # tiers' labels are already persisted, and re-running with
        # --only-instances resumes exactly where this stopped.
        infra_hit: dict[str, str] = {}
        for v in verdicts:
            if v["passed"]:
                continue
            for r in v.get("details", {}).get("rollouts", []):
                if r.get("infra_error"):
                    infra_hit[v["instance_id"]] = r["infra_error"]
                    break
        if infra_hit:
            causes = sorted(set(infra_hit.values()))
            raise RuntimeError(
                f"tier '{tier.label}' ({tier.agent}/{tier.model}): "
                f"{len(infra_hit)} instance(s) failed because the solver could "
                f"not run ({', '.join(causes)}) — not because the instances are "
                "unsolvable. Aborting cascade WITHOUT discarding so these are "
                "not lost. Fix the cause, then re-run the cascade with:\n"
                f"  --only-instances {','.join(sorted(infra_hit))}\n"
                "Labels assigned by earlier tiers are preserved; inspect logs "
                f"under validation/solver_agent/ in {ctx.run_dir}"
            )
        # Fallback for the older signature: a whole tier where nothing produced
        # an answer file and no signature was recognised.
        if verdicts and not passed and all(
            all("produced no answer.json" in r.get("reason", "")
                for r in v.get("details", {}).get("rollouts", [{}]))
            for v in verdicts
        ):
            raise RuntimeError(
                f"tier '{tier.label}' ({tier.agent}/{tier.model}): no rollout "
                f"produced an answer.json on any of {len(verdicts)} instance(s) "
                "— this looks like an infrastructure failure (check auth/agent "
                "install), not unsolvable instances. Aborting cascade without "
                "discarding; inspect the agent logs under "
                f"validation/solver_agent/ in {ctx.run_dir}"
            )

        pass_counts = {
            v["instance_id"]: v.get("details", {}).get("pass_count")
            for v in verdicts
        }
        for instance_id in passed + partial:
            is_partial = instance_id in partial
            record = {
                "difficulty": tier.partial_label if is_partial else tier.label,
                "tier_index": index,
                "agent": tier.agent,
                "model": tier.model,
                "rollouts": rollouts,
                "pass_count": pass_counts.get(instance_id),
                "partial_pass": is_partial,
                "timestamp": timestamp,
            }
            assignments[instance_id] = record
            _write_difficulty(ctx, instance_id, record)
        tier_summaries.append(_tier_summary(tier, index, passed, failed, partial))
        partial_note = (
            f", {len(partial)} partial-pass accepted as '{tier.partial_label}'"
            if tier.partial_label else ""
        )
        print(
            f"[cascade] tier '{tier.label}': {len(passed)} accepted"
            f"{partial_note}, {len(failed)} escalated"
        )
        # Only zero-pass instances escalate; partial passes are already labelled.
        remaining = failed

    rejected = list(remaining)
    if rejected:
        verb = "discarding" if discard else "keeping (no-discard)"
        print(f"[cascade] {len(rejected)} instance(s) failed every tier — {verb}")
        if discard:
            for instance_id in rejected:
                _discard(ctx, "cascade", "failed_all_tiers", instance_id)

    # Merge with any existing report: this run is authoritative only for the
    # instances in its scope; labels and rejections of instances outside the
    # scope (e.g. a previous tier's accepts when re-running only the rejects)
    # are preserved.
    report_path = ctx.run_dir / "difficulty_report.json"
    previous: dict = {}
    if report_path.is_file():
        try:
            previous = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    merged_assignments = {
        k: v for k, v in previous.get("assignments", {}).items() if k not in scope
    }
    merged_assignments.update(assignments)
    merged_rejected = [
        i for i in previous.get("rejected", []) if i not in scope
    ] + rejected

    cascade_report = {
        "run_dir": str(ctx.run_dir),
        "timestamp": timestamp,
        "rollouts": rollouts,
        "tiers": [
            {"label": t.label, "agent": t.agent, "model": t.model} for t in tiers
        ],
        "tier_results": tier_summaries,
        "scope": sorted(scope),
        "assignments": merged_assignments,
        "rejected": merged_rejected,
        "rejected_discarded": bool(discard and rejected),
        "remaining_instances": [p.name for p in ctx.instance_dirs()],
    }
    if previous.get("manually_excluded"):
        cascade_report["manually_excluded"] = previous["manually_excluded"]
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(cascade_report, f, indent=2)
        f.write("\n")
    return cascade_report


def _tier_summary(
    tier: CascadeTier, index: int, passed: list, failed: list,
    partial: Optional[list] = None,
) -> dict:
    partial = partial or []
    return {
        "tier_index": index,
        "label": tier.label,
        "partial_label": tier.partial_label,
        "agent": tier.agent,
        "model": tier.model,
        "ran_on": len(passed) + len(failed) + len(partial),
        "accepted": passed,
        "partial": partial,
        "escalated": failed,
    }


def _write_difficulty(ctx: ValidationContext, instance_id: str, record: dict) -> None:
    path = ctx.instances_dir / instance_id / "difficulty.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
