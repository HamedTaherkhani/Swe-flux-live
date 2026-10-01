#!/usr/bin/env python3
"""Do the pre-inference difficulty labels agree with the difficulty models
actually experience?

The intrinsic labels (easy / medium / hard / very_hard) are assigned from the
instance alone, before any model answers it. This script derives a second,
post-inference label for every instance from how the evaluated models did, and
measures how well the two agree.

Empirical difficulty of an instance = mean partial-credit score across the
evaluated models (an unanswered instance scores 0). The post-inference label is
obtained by ranking instances by that score and cutting the ranking into four
bins with the SAME sizes as the intrinsic bins, so both labelings have the same
marginal distribution and any agreement is not an artifact of bin sizes.

Reported:
  - Spearman rank correlation between the intrinsic score (combined and each
    component metric) and the empirical score, with a p-value;
  - agreement between the two labelings: exact, within one level, and Cohen's
    quadratic-weighted kappa;
  - the confusion matrix (intrinsic rows, post-inference columns);
  - mean partial credit and exact-match rate per intrinsic level, per model.

usage: difficulty_label_agreement.py [--complexity-report out/complexity_report.json]
         [--scope SCOPE ...] [--all-instances] [--output out/difficulty_label_agreement.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repogen.scoring.decompose import decompose  # noqa: E402
from repogen.validation import agent_validated_instances  # noqa: E402

LEVELS = ("easy", "medium", "hard", "very_hard")
METRICS = ("combined", "semantic_reasoning", "answer_construction", "repository_navigation")
DEFAULT_SCOPES = (
    "kimi/kimi-k3",
    "deepseek/deepseek-v4-flash",
    "fireworks/accounts_fireworks_models_gpt-oss-120b",
    "claude-code-noexec/claude-opus-5-5-medium",
)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def answer_path(run_dir: Path, scope: str, instance_id: str) -> Path:
    # Raw-LLM answers live under evaluation/llm/<provider>/<model>/; agent
    # answers under evaluation/<agent>-noexec/<model>/.
    base = run_dir / "evaluation"
    if not (base / scope).is_dir() and (base / "llm" / scope).is_dir():
        base = base / "llm"
    return base / scope / instance_id / "answer.json"


def instance_outcomes(run_dir: Path, instance_id: str, scopes, float_tol: float) -> dict:
    oracle = read_json(run_dir / "instances" / instance_id / "oracle.json", {})
    expected = oracle.get("oracle_answer") if isinstance(oracle, dict) else None
    out = {}
    for scope in scopes:
        path = answer_path(run_dir, scope, instance_id)
        predicted = read_json(path) if path.is_file() and path.stat().st_size > 0 else None
        if expected is None or predicted is None:
            out[scope] = {"exact": False, "partial": 0.0, "answered": predicted is not None}
            continue
        try:
            row = decompose(expected, predicted, float_tol=float_tol)
        except Exception:  # noqa: BLE001 — unparsable answer counts as wrong
            out[scope] = {"exact": False, "partial": 0.0, "answered": True}
            continue
        out[scope] = {"exact": bool(row["exact"]), "partial": float(row["score"]), "answered": True}
    return out


def post_inference_labels(records: list[dict], sizes: dict[str, int]) -> None:
    """Rank by empirical score (easiest first) and cut with the intrinsic bin sizes."""
    ordered = sorted(
        records,
        key=lambda r: (-r["empirical_partial"], -r["empirical_exact"], r["instance_id"]),
    )
    cursor = 0
    for level in LEVELS:
        for record in ordered[cursor:cursor + sizes[level]]:
            record["post_label"] = level
        cursor += sizes[level]


def weighted_kappa(a: list[int], b: list[int], k: int) -> float:
    observed = np.zeros((k, k))
    for x, y in zip(a, b):
        observed[x, y] += 1
    n = observed.sum()
    weights = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)])
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / n
    return float(1 - (weights * observed).sum() / (weights * expected).sum())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--complexity-report", type=Path, default=PROJECT_ROOT / "out" / "complexity_report.json")
    parser.add_argument("--scope", action="append", help="evaluation scope to include (repeatable)")
    parser.add_argument(
        "--all-instances", action="store_true",
        help="use every instance in the complexity report, not only the verified ones",
    )
    parser.add_argument("--float-tol", type=float, default=1e-6)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "out" / "difficulty_label_agreement.json")
    args = parser.parse_args()
    scopes = tuple(args.scope) if args.scope else DEFAULT_SCOPES

    report = read_json(args.complexity_report)
    if not report:
        print(f"ERROR: cannot read {args.complexity_report}", file=sys.stderr)
        return 2

    verified: dict[str, set] = {}
    records = []
    for item in report["instances"]:
        run_dir = Path(item["run_dir"])
        if not args.all_instances:
            if str(run_dir) not in verified:
                verified[str(run_dir)] = agent_validated_instances(run_dir) or set()
            if item["instance_id"] not in verified[str(run_dir)]:
                continue
        outcomes = instance_outcomes(run_dir, item["instance_id"], scopes, args.float_tol)
        records.append({
            "run_dir": str(run_dir),
            "instance_id": item["instance_id"],
            "intrinsic_scores": item["scores"],
            "intrinsic_label": item["difficulty"]["combined"],
            "outcomes": outcomes,
            "empirical_partial": float(np.mean([o["partial"] for o in outcomes.values()])),
            "empirical_exact": int(sum(o["exact"] for o in outcomes.values())),
        })
    if not records:
        print("ERROR: no instances selected", file=sys.stderr)
        return 2

    sizes = Counter(r["intrinsic_label"] for r in records)
    post_inference_labels(records, sizes)

    # Rank correlations between the intrinsic scores and the empirical score.
    empirical = np.array([r["empirical_partial"] for r in records])
    exact_counts = np.array([r["empirical_exact"] for r in records])
    correlations = {}
    for metric in METRICS:
        intrinsic = np.array([r["intrinsic_scores"][metric] for r in records])
        # Higher intrinsic score = harder; higher empirical score = easier, so a
        # good label set gives a NEGATIVE correlation. Report the sign flipped.
        rho_p, p_p = stats.spearmanr(intrinsic, -empirical)
        rho_e, p_e = stats.spearmanr(intrinsic, -exact_counts)
        correlations[metric] = {
            "spearman_vs_partial_credit": round(float(rho_p), 3), "p_value_partial": float(p_p),
            "spearman_vs_exact_count": round(float(rho_e), 3), "p_value_exact": float(p_e),
        }

    index = {level: i for i, level in enumerate(LEVELS)}
    a = [index[r["intrinsic_label"]] for r in records]
    b = [index[r["post_label"]] for r in records]
    confusion = [[0] * len(LEVELS) for _ in LEVELS]
    for x, y in zip(a, b):
        confusion[x][y] += 1
    agreement = {
        "exact": round(sum(x == y for x, y in zip(a, b)) / len(a), 3),
        "within_one_level": round(sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a), 3),
        "quadratic_weighted_kappa": round(weighted_kappa(a, b, len(LEVELS)), 3),
        "chance_exact": round(sum((sizes[l] / len(a)) ** 2 for l in LEVELS), 3),
    }

    per_level: dict = {}
    for level in LEVELS:
        rows = [r for r in records if r["intrinsic_label"] == level]
        per_level[level] = {"n": len(rows), "mean_partial_all_models": round(float(np.mean([r["empirical_partial"] for r in rows])), 3)}
        for scope in scopes:
            per_level[level][scope] = {
                "exact_rate": round(float(np.mean([r["outcomes"][scope]["exact"] for r in rows])), 3),
                "mean_partial": round(float(np.mean([r["outcomes"][scope]["partial"] for r in rows])), 3),
            }

    coverage = {scope: sum(r["outcomes"][scope]["answered"] for r in records) for scope in scopes}
    result = {
        "instances": len(records),
        "scopes": list(scopes),
        "answers_found": coverage,
        "bin_sizes": dict(sizes),
        "empirical_difficulty": "mean partial credit across scopes (unanswered = 0)",
        "post_inference_labels": "instances ranked by empirical difficulty, cut with the intrinsic bin sizes",
        "spearman": correlations,
        "label_agreement": agreement,
        "confusion_intrinsic_rows_post_columns": {"levels": list(LEVELS), "matrix": confusion},
        "per_intrinsic_level": per_level,
        "records": [
            {k: r[k] for k in ("run_dir", "instance_id", "intrinsic_label", "post_label", "empirical_partial", "empirical_exact", "outcomes")}
            for r in records
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"instances: {len(records)}  scopes: {len(scopes)}  answers found: {coverage}")
    print(f"bin sizes: {dict(sizes)}")
    print("\nSpearman rank correlation, intrinsic score vs empirical difficulty (positive = harder label, worse outcome):")
    for metric, c in correlations.items():
        print(f"  {metric:24s} partial credit rho={c['spearman_vs_partial_credit']:+.3f} (p={c['p_value_partial']:.1e})   "
              f"exact count rho={c['spearman_vs_exact_count']:+.3f} (p={c['p_value_exact']:.1e})")
    print("\nIntrinsic vs post-inference labels (same bin sizes):")
    print(f"  exact agreement {agreement['exact']:.1%} (chance {agreement['chance_exact']:.1%}), "
          f"within one level {agreement['within_one_level']:.1%}, weighted kappa {agreement['quadratic_weighted_kappa']:.3f}")
    print("  confusion (rows: intrinsic, cols: post-inference) " + " ".join(f"{l:>9s}" for l in LEVELS))
    for level, row in zip(LEVELS, confusion):
        print(f"    {level:10s}" + " ".join(f"{v:9d}" for v in row))
    print("\nOutcome by intrinsic level:")
    header = f"  {'level':10s} {'n':>4s} {'partial(all)':>13s}" + "".join(f" {s.split('/')[-1][:22]:>24s}" for s in scopes)
    print(header)
    for level in LEVELS:
        p = per_level[level]
        print(f"  {level:10s} {p['n']:4d} {p['mean_partial_all_models']:13.3f}"
              + "".join(f" {p[s]['exact_rate']:9.3f}/{p[s]['mean_partial']:<13.3f}" for s in scopes))
    print(f"\nwritten: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
