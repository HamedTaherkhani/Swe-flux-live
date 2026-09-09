#!/usr/bin/env python3
"""Recover validation bands from a cascade tier that aborted before checkpointing.

When a tier hits a provider usage limit the cascade aborts to avoid recording
refusals as solver failures. Historically that threw away every decision the
tier had ALREADY made, because bands were only written after the whole tier
returned. (The cascade now checkpoints each verdict as it lands, so this script
is only needed for runs produced before that change.)

The verdicts themselves survive in validation_report.json, which run_validators
writes before the cascade raises. This script replays them:

  passed (all rollouts matched)        -> <tier validation band>
  partial (>=1 pass, >=1 fail)         -> <tier partial validation band>
  zero-pass, no infra error            -> left UNASSIGNED (escalates)
  any rollout with an infra error      -> left UNASSIGNED and REPORTED, because
                                          that instance was never really run

Nothing is deleted, intrinsic difficulty files are never touched, and existing
validation bands are not overwritten unless --force.

Usage:
  python3 scripts/recover_cascade_labels.py out/rich/run_20260813_173533 \
      --label easy --partial-label medium
  # then re-run the cascade for the printed --only-instances set
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--label", default="haiku_all",
                    help="validation band for all-rollouts-passed")
    ap.add_argument("--partial-label", default="haiku_partial",
                    help="validation band for mixed rollouts ('' leaves unassigned)")
    ap.add_argument("--scope", default=None,
                    help="validation_report scope (agent/model) to replay; "
                         "default: the last run in the report")
    ap.add_argument("--force", action="store_true",
                    help="overwrite cascade validation checkpoints that exist")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    report_path = args.run_dir / "validation_report.json"
    if not report_path.is_file():
        print(f"no validation_report.json in {args.run_dir}")
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    runs = report["runs"] if isinstance(report, dict) else report
    run = next((r for r in reversed(runs) if r.get("scope") == args.scope),
               runs[-1]) if args.scope else runs[-1]

    agent, _, model = (run.get("scope") or "/").partition("/")
    timestamp = run.get("timestamp") or ""

    written, skipped, infra, escalate = [], [], [], []
    for verdict in run["verdicts"]:
        instance_id = verdict["instance_id"]
        details = verdict.get("details") or {}
        rollouts = details.get("rollouts") or []
        if any(r.get("infra_error") for r in rollouts):
            infra.append(instance_id)
            continue
        pass_count = details.get("pass_count", 0) or 0
        if verdict.get("passed"):
            label, partial = args.label, False
        elif pass_count > 0 and args.partial_label:
            label, partial = args.partial_label, True
        else:
            escalate.append(instance_id)
            continue

        if not (args.run_dir / "instances" / instance_id).is_dir():
            continue
        path = (
            args.run_dir / "validation" / "cascade" / "checkpoints"
            / f"{instance_id}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.force:
            skipped.append(instance_id)
            continue
        record = {
            "validation_band": label,
            "tier_index": 1,
            "agent": agent,
            "model": model,
            "rollouts": details.get("rollouts_required"),
            "pass_count": pass_count,
            "partial_pass": partial,
            "timestamp": timestamp,
            "recovered_from": "validation_report.json",
        }
        if not args.dry_run:
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        written.append((instance_id, label))

    if written and not args.dry_run:
        cascade_path = args.run_dir / "cascade_validation_report.json"
        cascade = json.loads(cascade_path.read_text(encoding="utf-8")) \
            if cascade_path.is_file() else {
                "schema_version": 2,
                "purpose": "solver_validation_only",
                "affects_difficulty": False,
                "run_dir": str(args.run_dir),
                "assignments": {},
                "rejected": [],
            }
        for instance_id, _ in written:
            checkpoint = (
                args.run_dir / "validation" / "cascade" / "checkpoints"
                / f"{instance_id}.json"
            )
            cascade.setdefault("assignments", {})[instance_id] = json.loads(
                checkpoint.read_text(encoding="utf-8")
            )
        cascade_path.write_text(json.dumps(cascade, indent=2) + "\n", encoding="utf-8")

    for instance_id, label in written:
        print(f"  {label:8} {instance_id}")
    print(f"\nrecovered {len(written)} validation band(s)"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    if skipped:
        print(f"skipped {len(skipped)} existing checkpoint(s) (use --force)")
    if escalate:
        print(f"\n{len(escalate)} zero-pass instance(s) left unassigned for the "
              f"next tier:\n  {','.join(sorted(escalate))}")
    if infra:
        print(f"\n{len(infra)} instance(s) never actually ran (provider refusal). "
              f"Re-run the tier for exactly these:\n  --only-instances "
              f"{','.join(sorted(infra))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
