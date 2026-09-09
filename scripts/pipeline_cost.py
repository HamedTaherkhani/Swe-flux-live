#!/usr/bin/env python3
"""Compute the per-stage token cost of a repogen run (generation + validation).

Only stages that consume paid model tokens are priced:

  generate  cursor / gpt-5.6-sol   -- priced here from token counts
  cascade   claude-code / haiku    -- cost reported by the Claude Code SDK
            claude-code / fable

The screen stage runs no model, and the kimi evaluation stage is deliberately
excluded (it is measurement, not benchmark construction).

WHERE THE NUMBERS COME FROM
---------------------------
generation: every instance writes logs/<id>/<id>.traj.json. Its final event is
  the SDK's `result` event, carrying CUMULATIVE session token counts:
      inputTokens, outputTokens, cacheWriteTokens, cacheReadTokens
  These are exact per-instance totals for the whole agent session, not a sample.
  Cursor bills gpt-5.6-sol out of its "Other Models" third-party pool at the
  published per-million rates below, so cost is a direct arithmetic product.
  NOTE: cacheReadTokens are billed INSTEAD OF, not in addition to, inputTokens
  for the cached portion, which is why the four buckets are summed separately.

validation: every rollout writes validation/solver_agent/claude-code/<model>/
  <instance>/rollout_N/<id>.traj.json, whose `result` event carries
  `total_cost_usd` already computed by the Claude Code SDK against Anthropic's
  own billing. That is authoritative, so it is used directly rather than
  re-derived from token counts (which would require guessing the cache mix).
  Rollouts that died on a provider refusal report total_cost_usd == 0 and are
  counted separately so they do not depress the per-instance average.

Usage:
  python3 scripts/pipeline_cost.py out/fastapi/run_20260811_154129
  python3 scripts/pipeline_cost.py --repo fastapi
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Cursor per-million-token rates for GPT-5.6 Sol, from
# https://cursor.com/docs/account/pricing (retrieved 2026-08-13).
SOL_USD_PER_MTOK = {
    "input": 5.00,
    "cache_write": 6.25,
    "cache_read": 0.50,
    "output": 30.00,
}
# Long context: above this many input tokens, input doubles and output is 1.5x.
SOL_LONG_CONTEXT_THRESHOLD = 272_000
SOL_LONG_CONTEXT_INPUT_MULT = 2.0
SOL_LONG_CONTEXT_OUTPUT_MULT = 1.5


def _result_event(traj_path: Path) -> dict:
    """Return the SDK `result` event (last event carrying the session totals)."""
    try:
        doc = json.loads(traj_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    events = doc.get("events") if isinstance(doc, dict) else doc
    if not isinstance(events, list):
        return {}
    for event in reversed(events):
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    return {}


def sol_cost(usage: dict, long_context: bool = False) -> tuple[float, dict]:
    """Price one gpt-5.6-sol session. Returns (usd, per-bucket breakdown).

    `long_context` applies Cursor's >272k surcharge (input x2, output x1.5).

    IMPORTANT: whether that surcharge actually applied CANNOT be determined from
    our artifacts. The surcharge is per REQUEST, but a cursor trajectory records
    exactly one usage block -- the final `result` event, holding cumulative
    session totals over hundreds of requests. Summed cache reads therefore
    exceed 272k on nearly every session while each individual request may have
    been far below it. Comparing the session total against the threshold would
    silently overstate cost, so the caller must choose explicitly; the default
    (False) is the lower bound.
    """
    tok = {
        "input": int(usage.get("inputTokens", 0) or 0),
        "cache_write": int(usage.get("cacheWriteTokens", 0) or 0),
        "cache_read": int(usage.get("cacheReadTokens", 0) or 0),
        "output": int(usage.get("outputTokens", 0) or 0),
    }
    rates = dict(SOL_USD_PER_MTOK)
    if long_context:
        rates["input"] *= SOL_LONG_CONTEXT_INPUT_MULT
        rates["cache_write"] *= SOL_LONG_CONTEXT_INPUT_MULT
        rates["cache_read"] *= SOL_LONG_CONTEXT_INPUT_MULT
        rates["output"] *= SOL_LONG_CONTEXT_OUTPUT_MULT
    breakdown = {k: tok[k] / 1_000_000 * rates[k] for k in tok}
    return sum(breakdown.values()), {"tokens": tok, "usd_by_bucket": breakdown,
                                     "long_context": long_context}


def generation_costs(run_dir: Path, long_context: bool = False) -> dict:
    """Per-instance generation cost, keyed by instance id."""
    out = {}
    for traj in sorted(run_dir.glob("logs/*/*.traj.json")):
        instance = traj.parent.name
        usage = _result_event(traj).get("usage") or {}
        if not usage:
            continue
        usd, detail = sol_cost(usage, long_context=long_context)
        out[instance] = {"usd": usd, **detail}
    return out


def validation_costs(run_dir: Path) -> dict:
    """Per-(tier, instance) validation cost from Claude Code's own accounting."""
    base = run_dir / "validation" / "solver_agent" / "claude-code"
    tiers: dict[str, dict] = {}
    for model_dir in sorted(p for p in base.glob("*") if p.is_dir()):
        per_instance: dict[str, dict] = defaultdict(
            lambda: {"usd": 0.0, "rollouts": 0, "zero_cost_rollouts": 0}
        )
        for traj in sorted(model_dir.glob("*/rollout_*/*.traj.json")):
            instance = traj.parent.parent.name
            usd = float(_result_event(traj).get("total_cost_usd", 0.0) or 0.0)
            rec = per_instance[instance]
            rec["usd"] += usd
            rec["rollouts"] += 1
            if usd == 0.0:
                rec["zero_cost_rollouts"] += 1
        tiers[model_dir.name] = dict(per_instance)
    return tiers


def _fmt(x: float) -> str:
    return f"${x:,.4f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", nargs="?", help="path to out/<repo>/run_<stamp>")
    ap.add_argument("--repo", help="use the latest run of this repo under out/")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--long-context", action="store_true",
                    help="assume EVERY generation request paid Cursor's >272k "
                         "surcharge (input x2, output x1.5). Our artifacts "
                         "cannot tell us whether it applied, so the default "
                         "(off) is the lower bound and this flag is the upper "
                         "bound; true cost lies between them.")
    args = ap.parse_args()

    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.repo:
        runs = sorted(Path("out", args.repo).glob("run_*"))
        if not runs:
            print(f"no runs under out/{args.repo}", file=sys.stderr)
            return 2
        run_dir = runs[-1]
    else:
        ap.error("give a run_dir or --repo")
    if not run_dir.is_dir():
        print(f"not a directory: {run_dir}", file=sys.stderr)
        return 2

    gen = generation_costs(run_dir, long_context=args.long_context)
    val = validation_costs(run_dir)

    gen_total = sum(v["usd"] for v in gen.values())
    gen_n = len(gen)
    tier_totals = {
        tier: sum(v["usd"] for v in per.values()) for tier, per in val.items()
    }
    val_total = sum(tier_totals.values())

    if args.json:
        print(json.dumps({
            "run_dir": str(run_dir),
            "pricing_gpt_5_6_sol_usd_per_mtok": SOL_USD_PER_MTOK,
            "generation": {"instances": gen_n, "total_usd": gen_total,
                           "per_instance": gen},
            "validation": {"total_usd": val_total, "tiers": val},
            "pipeline_total_usd": gen_total + val_total,
        }, indent=2))
        return 0

    print(f"run: {run_dir}")
    print(f"pricing: gpt-5.6-sol @ input ${SOL_USD_PER_MTOK['input']}/Mtok, "
          f"cache_write ${SOL_USD_PER_MTOK['cache_write']}, "
          f"cache_read ${SOL_USD_PER_MTOK['cache_read']}, "
          f"output ${SOL_USD_PER_MTOK['output']} (cursor.com/docs/account/pricing)")
    print()

    print("== GENERATION (cursor / gpt-5.6-sol)")
    tok_tot = defaultdict(int)
    usd_tot = defaultdict(float)
    long_ctx = 0
    for v in gen.values():
        for k, n in v["tokens"].items():
            tok_tot[k] += n
        for k, u in v["usd_by_bucket"].items():
            usd_tot[k] += u
        long_ctx += bool(v["long_context"])
    print(f"  instances with usage recorded: {gen_n}")
    for k in ("input", "cache_write", "cache_read", "output"):
        print(f"    {k:12} {tok_tot[k]:>12,} tok  ->  {_fmt(usd_tot[k]):>12}")
    print(f"  long-context surcharge applied: "
          f"{'YES (upper bound)' if args.long_context else 'no (lower bound)'}")
    print(f"  TOTAL {_fmt(gen_total)}   AVG/instance {_fmt(gen_total / gen_n) if gen_n else 'n/a'}")
    print()

    print("== VALIDATION (claude-code, cost reported by the SDK)")
    for tier, per in val.items():
        n_inst = len(per)
        n_roll = sum(v["rollouts"] for v in per.values())
        n_zero = sum(v["zero_cost_rollouts"] for v in per.values())
        total = tier_totals[tier]
        print(f"  {tier}")
        print(f"    instances {n_inst:>3} | rollouts {n_roll:>4}"
              f" | zero-cost rollouts {n_zero:>3}")
        print(f"    TOTAL {_fmt(total)} | avg/instance "
              f"{_fmt(total / n_inst) if n_inst else 'n/a'} | avg/rollout "
              f"{_fmt(total / n_roll) if n_roll else 'n/a'}")
    print(f"  VALIDATION TOTAL {_fmt(val_total)}")
    print()

    kept = len([p for p in (run_dir / "instances").glob("*") if p.is_dir()
                and p.name != "shared"])
    print("== PIPELINE (generation + validation, no evaluation)")
    print(f"  TOTAL {_fmt(gen_total + val_total)}")
    if gen_n:
        print(f"  per generated instance ({gen_n}): "
              f"{_fmt((gen_total + val_total) / gen_n)}")
    if kept:
        print(f"  per SURVIVING instance ({kept}): "
              f"{_fmt((gen_total + val_total) / kept)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
