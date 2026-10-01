#!/usr/bin/env python3
"""Fit the calibrated difficulty score and freeze its coefficients.

The calibrated score is a ridge regression that predicts how well the
evaluated models do on an instance (the mean of their partial-credit score and
their exact-match rate, so that both stay monotone across the difficulty
levels), from signals available before any inference:

    expected_success = intercept
                     + sum_i  w_i * z(log1p(feature_i))
                     + offset[answer_archetype]

with three features (answer string characters, answer leaf count, executed
line events) and one additive offset per answer archetype. The difficulty
score reported by `repogen complexity` is 10 * (1 - expected_success), so a
higher score means harder, on the same 0..10 scale as the component metrics.

The fit is validated out of sample with leave-one-repository-out folds (the
ridge strength is chosen on those folds too), and the frozen coefficients are
written to repogen/difficulty_calibration.json together with the validation
numbers. Re-run this script when the evaluated models change.

usage: calibrate_difficulty.py [--complexity-report out/complexity_report.json]
         [--scope SCOPE ...] [--output repogen/difficulty_calibration.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from difficulty_label_agreement import DEFAULT_SCOPES, instance_outcomes, read_json  # noqa: E402
from repogen.complexity import CALIBRATION_FEATURES, calibration_inputs  # noqa: E402
from repogen.validation import agent_validated_instances  # noqa: E402

ALPHAS = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]


def ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, float]:
    """Ridge with an unpenalized intercept: centre, solve, recover the intercept."""
    x_mean, y_mean = X.mean(axis=0), y.mean()
    Xc, yc = X - x_mean, y - y_mean
    w = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(X.shape[1]), Xc.T @ yc)
    return w, float(y_mean - x_mean @ w)


def design(records: list[dict], archetypes: list[str], mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    numeric = np.array([[np.log1p(max(0.0, r["inputs"][f])) for f in CALIBRATION_FEATURES] for r in records])
    numeric = (numeric - mean) / std
    onehot = np.array([[1.0 if r["archetype"] == a else 0.0 for a in archetypes] for r in records])
    return np.hstack([numeric, onehot])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--complexity-report", type=Path, default=PROJECT_ROOT / "out" / "complexity_report.json")
    parser.add_argument("--scope", action="append", help="evaluation scope whose outcomes define the target (repeatable)")
    parser.add_argument("--float-tol", type=float, default=1e-6)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "repogen" / "difficulty_calibration.json")
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
        if str(run_dir) not in verified:
            verified[str(run_dir)] = agent_validated_instances(run_dir) or set()
        if item["instance_id"] not in verified[str(run_dir)]:
            continue
        outcomes = instance_outcomes(run_dir, item["instance_id"], scopes, args.float_tol)
        records.append({
            "repo": run_dir.parts[-2] if len(run_dir.parts) >= 2 else str(run_dir),
            "instance_id": item["instance_id"],
            "archetype": item["answer_archetype"],
            "inputs": calibration_inputs(item["features"]),
            "partial": float(np.mean([o["partial"] for o in outcomes.values()])),
            "exact": float(np.mean([o["exact"] for o in outcomes.values()])),
        })
    for record in records:
        record["target"] = 0.5 * record["partial"] + 0.5 * record["exact"]
    if len(records) < 50:
        print(f"ERROR: only {len(records)} verified instances with outcomes", file=sys.stderr)
        return 2

    archetypes = sorted({r["archetype"] for r in records})
    raw = np.array([[np.log1p(max(0.0, r["inputs"][f])) for f in CALIBRATION_FEATURES] for r in records])
    mean, std = raw.mean(axis=0), raw.std(axis=0)
    std[std == 0] = 1.0
    X = design(records, archetypes, mean, std)
    y = np.array([r["target"] for r in records])
    partial = np.array([r["partial"] for r in records])
    exact = np.array([r["exact"] for r in records])
    repos = np.array([r["repo"] for r in records])

    # Leave-one-repository-out: choose alpha by held-out rank correlation.
    loro, loro_partial, loro_exact = {}, {}, {}
    for alpha in ALPHAS:
        pred = np.zeros(len(y))
        for repo in sorted(set(repos)):
            train, test = repos != repo, repos == repo
            w, b = ridge_fit(X[train], y[train], alpha)
            pred[test] = X[test] @ w + b
        loro[alpha] = float(stats.spearmanr(pred, y)[0])
        loro_partial[alpha] = float(stats.spearmanr(pred, partial)[0])
        loro_exact[alpha] = float(stats.spearmanr(pred, exact)[0])
    alpha = max(loro, key=loro.get)
    w, b = ridge_fit(X, y, alpha)
    fitted = X @ w + b
    in_sample = float(stats.spearmanr(fitted, y)[0])

    n_feat = len(CALIBRATION_FEATURES)
    calibration = {
        "schema_version": 1,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "method": "ridge regression of mean partial credit on log1p features (standardized) plus answer-archetype offsets",
        "target": {"scopes": list(scopes), "definition": "0.5 * mean partial-credit score + 0.5 * exact-match rate across scopes; unanswered = 0"},
        "fitted_on": {"complexity_report": str(args.complexity_report), "instances": len(records),
                      "repositories": sorted(set(repos)), "archetypes": Counter(r["archetype"] for r in records)},
        "features": list(CALIBRATION_FEATURES),
        "transform": "log1p, then standardize with feature_mean/feature_std",
        "feature_mean": [round(float(v), 6) for v in mean],
        "feature_std": [round(float(v), 6) for v in std],
        "coefficients": [round(float(v), 6) for v in w[:n_feat]],
        "archetype_offsets": {a: round(float(v), 6) for a, v in zip(archetypes, w[n_feat:])},
        "unknown_archetype_offset": 0.0,
        "intercept": round(b, 6),
        "ridge_alpha": alpha,
        "score": "10 * (1 - expected_success); higher = harder",
        "validation": {
            "leave_one_repository_out_spearman_by_alpha": {str(k): round(v, 4) for k, v in loro.items()},
            "leave_one_repository_out_spearman": round(loro[alpha], 4),
            "leave_one_repository_out_spearman_vs_partial_credit": round(loro_partial[alpha], 4),
            "leave_one_repository_out_spearman_vs_exact_match": round(loro_exact[alpha], 4),
            "in_sample_spearman": round(in_sample, 4),
            "in_sample_spearman_vs_partial_credit": round(float(stats.spearmanr(fitted, partial)[0]), 4),
            "in_sample_spearman_vs_exact_match": round(float(stats.spearmanr(fitted, exact)[0]), 4),
        },
    }
    args.output.write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")

    print(f"fitted on {len(records)} verified instances from {len(set(repos))} repositories, {len(archetypes)} archetypes")
    print(f"ridge alpha {alpha} (chosen on leave-one-repo-out folds)")
    print("coefficients (standardized log1p features; negative = harder):")
    for name, coef in zip(CALIBRATION_FEATURES, w[:n_feat]):
        print(f"  {coef:+.4f}  {name}")
    print("archetype offsets (largest to smallest):")
    for name, coef in sorted(zip(archetypes, w[n_feat:]), key=lambda t: -t[1]):
        print(f"  {coef:+.4f}  {name}")
    print(f"Spearman vs target: leave-one-repo-out {loro[alpha]:.3f}, in-sample {in_sample:.3f}")
    print(f"  leave-one-repo-out vs partial credit {loro_partial[alpha]:.3f}, vs exact match {loro_exact[alpha]:.3f}")
    print(f"written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
