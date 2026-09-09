#!/usr/bin/env bash
# Full SWE-Flux-Live pipeline for one repo:
#   generate -> screen -> Haiku/Fable solvability validation -> intrinsic
#   four-level difficulty -> Kimi evaluation. Agent cascade outcomes never set
#   difficulty; they are retained only as validation evidence.
#
# Usage: scripts/run_full_pipeline.sh <repo> [num_instances]
#   <repo>           repo key in repositories.json (e.g. haystack, instruct_lab)
#   [num_instances]  instances to generate (default 40)
#
# Env switches:
#   SKIP_FABLE=1     stop validation after Haiku: no Fable tier
#                    is run, so no fable quota is spent. Zero-pass instances are
#                    kept (--no-discard), and a command to validate them with
#                    Fable later is printed at the end.
#
# Auth comes from .env: cursor subscription session (generation),
# CLAUDE_CODE_OAUTH_TOKEN (cascade), MOONSHOT_API_KEY (evaluation).
set -uo pipefail
cd "$(dirname "$0")/.."

REPO="${1:?usage: $0 <repo> [num_instances]}"
COUNT="${2:-40}"
SKIP_FABLE="${SKIP_FABLE:-0}"

GEN_AGENT=cursor
GEN_MODEL=gpt-5.6-sol-medium
# One container per worker: ~150-200MB RAM each on a light repo, ~500-700MB on
# an ML repo (torch/transformers). 3 workers fit comfortably in 2GB.
GEN_PARALLEL=3
TIER1=haiku_all/haiku_partial=claude-code:claude-haiku-4-5-20251001
TIER2=fable_all=claude-code:claude-fable-5
SOLVER_EFFORT=medium
ROLLOUTS=3
# Solver containers are ~315MB and <1% CPU each (the work is API wait, not
# local compute), so the real limit is the Claude subscription quota, not RAM.
CASCADE_PARALLEL=4
EVAL_MODEL=kimi-k3
EVAL_EFFORT=low
EVAL_PARALLEL=4
export REPOBEHAVE_KIMI_REQUEST_TIMEOUT_SECONDS=900

echo "=== [1/5] generate: $COUNT instances on '$REPO' ($GEN_AGENT/$GEN_MODEL, parallel $GEN_PARALLEL)"
python3 -u -m repogen generate --repo "$REPO" \
  --agent "$GEN_AGENT" --model "$GEN_MODEL" \
  --num-instances "$COUNT" --parallel "$GEN_PARALLEL"
rc=$?; [ $rc -ne 0 ] && { echo "FAILED: generate (exit $rc)"; exit $rc; }

echo "=== [2/5] screen"
python3 -u -m repogen screen --repo "$REPO"
rc=$?; [ $rc -ne 0 ] && { echo "FAILED: screen (exit $rc)"; exit $rc; }

if [ "$SKIP_FABLE" = "1" ]; then
  # Haiku tier only. It is the LAST tier here, so zero-pass instances would be
  # "rejected — failed every tier" and moved out of instances/; --no-discard
  # keeps them on disk for later Fable validation. Intrinsic labels are separate.
  echo "=== [3/5] validation cascade (SKIP_FABLE): r$ROLLOUTS p$CASCADE_PARALLEL, $TIER1 only"
  python3 -u -m repogen cascade --repo "$REPO" \
    --tier "$TIER1" \
    --solver-effort "$SOLVER_EFFORT" --rollouts "$ROLLOUTS" \
    --parallel "$CASCADE_PARALLEL" --no-discard
  rc=$?; [ $rc -ne 0 ] && { echo "FAILED: cascade (exit $rc)"; exit $rc; }
  # Haiku zero-pass instances remain unevaluated until a later Fable rollout
  # validates them. Kimi always stays behind the validation gate.
  EVAL_SCOPE=
else
  echo "=== [3/5] validation cascade: r$ROLLOUTS p$CASCADE_PARALLEL, $TIER1 -> $TIER2"
  python3 -u -m repogen cascade --repo "$REPO" \
    --tier "$TIER1" --tier "$TIER2" \
    --solver-effort "$SOLVER_EFFORT" --rollouts "$ROLLOUTS" \
    --parallel "$CASCADE_PARALLEL"
  rc=$?; [ $rc -ne 0 ] && { echo "FAILED: cascade (exit $rc) — if this was an "\
"infra abort (auth/usage limit), fix the cause and re-run: python3 -m repogen "\
"cascade --repo $REPO --tier '$TIER1' --tier '$TIER2' --solver-effort "\
"$SOLVER_EFFORT --rollouts $ROLLOUTS --parallel $CASCADE_PARALLEL"; exit $rc; }
  EVAL_SCOPE=
fi

echo "=== [4/5] intrinsic four-level difficulty"
python3 -u -m repogen complexity --all-runs --output-root out
rc=$?; [ $rc -ne 0 ] && { echo "FAILED: intrinsic difficulty (exit $rc)"; exit $rc; }

echo "=== [5/5] evaluate: $EVAL_MODEL $EVAL_EFFORT effort, parallel $EVAL_PARALLEL"
python3 -u -m repogen evaluate --repo "$REPO" \
  --llm-provider kimi --llm-model "$EVAL_MODEL" \
  --llm-reasoning-effort "$EVAL_EFFORT" --parallel "$EVAL_PARALLEL" $EVAL_SCOPE
rc=$?; [ $rc -ne 0 ] && { echo "FAILED: evaluate (exit $rc)"; exit $rc; }

# Labels stay unchanged; this refresh only joins the new held-out Kimi results.
python3 -u -m repogen complexity --all-runs --output-root out \
  --evaluation-scope kimi/kimi-k3

if [ "$SKIP_FABLE" = "1" ]; then
  RUN_DIR=$(ls -d out/"$REPO"/run_* 2>/dev/null | tail -1)
  UNVALIDATED=$(python3 - "$RUN_DIR" <<'PY'
import json, os, sys
path = os.path.join(sys.argv[1], "cascade_validation_report.json")
data = json.load(open(path)) if os.path.isfile(path) else {}
print(",".join(sorted(data.get("rejected", []))))
PY
)
  if [ -n "$UNVALIDATED" ]; then
    echo "=== SKIP_FABLE: instances with zero Haiku passes."
    echo "    They are intrinsically labelled but still need Fable validation:"
    echo "    python3 -m repogen cascade --run-dir $RUN_DIR \\"
    echo "      --tier '$TIER2' --solver-effort $SOLVER_EFFORT \\"
    echo "      --rollouts $ROLLOUTS --parallel $CASCADE_PARALLEL \\"
    echo "      --only-instances $UNVALIDATED"
  fi
fi

echo "=== DONE"
