"""Deterministic allocation of (category x target) pairs.

Given the scout's target inventory, produce a plan of N instances that is:
- diverse: each function used once, capped instances per module/file,
- well-matched: each category only gets targets that structurally fit it,
- hard: within eligible targets, higher structural scores are preferred,
- reproducible: seeded jitter breaks ties, same seed -> same plan.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from .config import sanitize_slug

Metrics = dict


@dataclass(frozen=True)
class CategoryProfile:
    """Structural fit of one question category (Strategy objects, data-driven)."""

    name: str
    eligible: Callable[[Metrics], bool]
    affinity: Callable[[Metrics], float]
    id_slug: str


def _m(metrics: Metrics, key: str) -> float:
    return float(metrics.get(key, 0) or 0)


CATEGORY_PROFILES: dict[str, CategoryProfile] = {
    profile.name: profile
    for profile in [
        CategoryProfile(
            "S1_IntraProceduralCFG",
            eligible=lambda m: _m(m, "branches") >= 2,
            affinity=lambda m: _m(m, "branches") * 2 + _m(m, "boolops") + _m(m, "returns"),
            id_slug="s1_cfg",
        ),
        CategoryProfile(
            "S2_Loops",
            eligible=lambda m: _m(m, "loops") >= 1,
            affinity=lambda m: _m(m, "loops") * 2
            + _m(m, "while_loops") * 2
            + _m(m, "max_loop_nesting") * 3
            + _m(m, "breaks_continues"),
            id_slug="s2_loops",
        ),
        CategoryProfile(
            "S3_ProgramState",
            eligible=lambda m: _m(m, "assigns") + _m(m, "augassigns") >= 4,
            affinity=lambda m: _m(m, "assigns") + _m(m, "augassigns") * 2 + _m(m, "branches"),
            id_slug="s3_state",
        ),
        CategoryProfile(
            "S4_DataFlow",
            eligible=lambda m: _m(m, "assigns") >= 3 and _m(m, "branches") >= 1,
            affinity=lambda m: _m(m, "assigns") + _m(m, "branches") * 2 + _m(m, "loops"),
            id_slug="s4_dataflow",
        ),
        CategoryProfile(
            "S5_Exceptions",
            eligible=lambda m: _m(m, "raises") + _m(m, "excepts") >= 1,
            affinity=lambda m: _m(m, "raises") * 2
            + _m(m, "excepts") * 2
            + _m(m, "finallys") * 3
            + _m(m, "branches"),
            id_slug="s5_exceptions",
        ),
        CategoryProfile(
            "S6_InterProceduralCFG",
            eligible=lambda m: _m(m, "num_local_calls") >= 1,
            affinity=lambda m: _m(m, "num_local_calls") * 3 + _m(m, "branches"),
            id_slug="s6_calls",
        ),
        CategoryProfile(
            "M1_IntraProceduralCFG",
            eligible=lambda m: _m(m, "branches") >= 4,
            affinity=lambda m: _m(m, "branches") * 2
            + _m(m, "boolops") * 2
            + _m(m, "returns")
            + _m(m, "body_lines") / 10,
            id_slug="m1_cfg",
        ),
        CategoryProfile(
            "M2_Loops",
            eligible=lambda m: _m(m, "loops") >= 2 or _m(m, "max_loop_nesting") >= 2,
            affinity=lambda m: _m(m, "loops") * 2
            + _m(m, "max_loop_nesting") * 4
            + _m(m, "breaks_continues") * 2,
            id_slug="m2_loops",
        ),
        CategoryProfile(
            "M3_ProgramState",
            eligible=lambda m: _m(m, "assigns") + _m(m, "augassigns") >= 6,
            affinity=lambda m: _m(m, "assigns")
            + _m(m, "augassigns") * 2
            + _m(m, "branches") * 2
            + _m(m, "loops"),
            id_slug="m3_state",
        ),
        CategoryProfile(
            "M4_DataFlow",
            eligible=lambda m: _m(m, "assigns") >= 5 and _m(m, "branches") >= 2,
            affinity=lambda m: _m(m, "assigns") * 2 + _m(m, "branches") * 2 + _m(m, "loops") * 2,
            id_slug="m4_dataflow",
        ),
        CategoryProfile(
            "M5_Exceptions",
            eligible=lambda m: _m(m, "raises") + _m(m, "excepts") >= 2,
            affinity=lambda m: _m(m, "raises") * 2
            + _m(m, "excepts") * 3
            + _m(m, "finallys") * 3
            + _m(m, "num_local_calls"),
            id_slug="m5_exceptions",
        ),
        CategoryProfile(
            "M6_InterProceduralCFG",
            eligible=lambda m: _m(m, "num_local_calls") >= 2,
            affinity=lambda m: _m(m, "num_local_calls") * 4
            + _m(m, "branches")
            + _m(m, "excepts"),
            id_slug="m6_calls",
        ),
        CategoryProfile(
            "M7_Invariants",
            eligible=lambda m: _m(m, "loops") >= 1
            and _m(m, "assigns") + _m(m, "augassigns") >= 3,
            affinity=lambda m: _m(m, "loops") * 2
            + _m(m, "augassigns") * 3
            + _m(m, "assigns")
            + _m(m, "max_loop_nesting") * 2,
            id_slug="m7_invariants",
        ),
    ]
}


@dataclass
class PlannedInstance:
    instance_id: str
    category: str
    target: dict
    rank_note: str = ""

    def as_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "category": self.category,
            "target": self.target,
            "rank_note": self.rank_note,
        }


@dataclass
class Planner:
    num_instances: int
    categories: list[str]
    seed: int = 7
    max_per_module: int = 3
    max_per_file: int = 2

    _used_functions: set = field(default_factory=set, init=False)
    _module_counts: dict = field(default_factory=dict, init=False)
    _file_counts: dict = field(default_factory=dict, init=False)
    _used_ids: set = field(default_factory=set, init=False)

    def plan(self, targets: list[dict]) -> list[PlannedInstance]:
        rng = random.Random(self.seed)
        quotas = self._quotas(targets)
        planned: list[PlannedInstance] = []

        # Round-robin across categories so no category exhausts the good
        # targets before others get a pick.
        remaining = dict(quotas)
        order = [c for c in self.categories if remaining.get(c, 0) > 0]
        while order:
            for category in list(order):
                if remaining[category] <= 0:
                    order.remove(category)
                    continue
                pick = self._pick(category, targets, rng)
                if pick is None:
                    remaining[category] = 0
                    order.remove(category)
                    continue
                planned.append(pick)
                remaining[category] -= 1
                if remaining[category] <= 0:
                    order.remove(category)

        # Backfill if some categories ran dry of eligible targets.
        deficit = self.num_instances - len(planned)
        if deficit > 0:
            fallback_order = sorted(
                self.categories,
                key=lambda c: -self._eligible_count(c, targets),
            )
            while deficit > 0:
                progressed = False
                for category in fallback_order:
                    pick = self._pick(category, targets, rng)
                    if pick is not None:
                        pick.rank_note += " (backfill)"
                        planned.append(pick)
                        deficit -= 1
                        progressed = True
                        if deficit == 0:
                            break
                if not progressed:
                    break
        return planned

    # -- internals -----------------------------------------------------

    def _quotas(self, targets: list[dict]) -> dict[str, int]:
        base = self.num_instances // len(self.categories)
        extra = self.num_instances - base * len(self.categories)
        richness = sorted(
            self.categories,
            key=lambda c: -self._eligible_count(c, targets),
        )
        quotas = {c: base for c in self.categories}
        for category in richness[:extra]:
            quotas[category] += 1
        return quotas

    def _eligible_count(self, category: str, targets: list[dict]) -> int:
        profile = CATEGORY_PROFILES[category]
        return sum(1 for t in targets if profile.eligible(t["metrics"]))

    def _pick(
        self, category: str, targets: list[dict], rng: random.Random
    ) -> Optional[PlannedInstance]:
        profile = CATEGORY_PROFILES[category]
        best = None
        best_score = float("-inf")
        for target in targets:
            key = (target["file"], target["qualname"])
            if key in self._used_functions:
                continue
            if self._module_counts.get(target["module"], 0) >= self.max_per_module:
                continue
            if self._file_counts.get(target["file"], 0) >= self.max_per_file:
                continue
            metrics = target["metrics"]
            if not profile.eligible(metrics):
                continue
            score = (
                profile.affinity(metrics)
                + float(target.get("score", 0)) * 0.5
                + rng.uniform(0, 1.5)  # seeded jitter: variety across runs
            )
            if score > best_score:
                best, best_score = target, score
        if best is None:
            return None

        key = (best["file"], best["qualname"])
        self._used_functions.add(key)
        self._module_counts[best["module"]] = self._module_counts.get(best["module"], 0) + 1
        self._file_counts[best["file"]] = self._file_counts.get(best["file"], 0) + 1

        instance_id = self._instance_id(best, profile)
        return PlannedInstance(
            instance_id=instance_id,
            category=category,
            target=best,
            rank_note=f"affinity+score={best_score:.1f}",
        )

    def _instance_id(self, target: dict, profile: CategoryProfile) -> str:
        module_tail = target["module"].split(".")[-1] or "mod"
        base = sanitize_slug(f"{module_tail}_{target['name']}_{profile.id_slug}")
        candidate = base
        counter = 2
        while candidate in self._used_ids:
            candidate = f"{base}_{counter}"
            counter += 1
        self._used_ids.add(candidate)
        return candidate
