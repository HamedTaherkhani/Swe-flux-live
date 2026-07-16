#!/usr/bin/env bash
set -euo pipefail

# Full instance pipeline: generate -> screen -> validate.
# All unrecognized arguments are forwarded to `repogen generate`; the newest
# run directory is then screened, and (if --solver-model is given) validated
# with a solver agent whose answers must match the oracle. Example:
#
#   ./scripts/generate_and_screen.sh \
#     --repo faker_qa --agent cursor --model gpt-5.3-codex-high --num-instances 40 \
#     --solver-model claude-sonnet-4-6
#
# Pipeline flags (not forwarded to generate):
#   --screen-dry-run           report screening verdicts without moving instances
#   --solver-model <model>     enable validation with this solver model
#   --solver-agent <backend>   solver backend (default: claude-code)
#   --solver-timeout <secs>    per-instance solver timeout (default: 900)
#   --validators <names>       comma-separated validators (default: solver_agent)
#   --validate-dry-run         report validation verdicts without discarding
#   --skip-screen              skip the screening stage
#   --skip-validate            skip the validation stage

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

REPO=""
OUTPUT_ROOT="$PROJECT_ROOT/out"
SCREEN_DRY_RUN=0
VALIDATE_DRY_RUN=0
SKIP_SCREEN=0
SKIP_VALIDATE=0
SOLVER_MODEL=""
SOLVER_AGENT="claude-code"
SOLVER_TIMEOUT="900"
VALIDATORS="solver_agent"
GEN_ARGS=()

args=("$@")
i=0
while (( i < ${#args[@]} )); do
  arg="${args[$i]}"
  case "$arg" in
    --repo)
      REPO="${args[$((i + 1))]:-}"
      GEN_ARGS+=("$arg" "$REPO")
      i=$((i + 2))
      ;;
    --output-root)
      OUTPUT_ROOT="${args[$((i + 1))]:-}"
      GEN_ARGS+=("$arg" "$OUTPUT_ROOT")
      i=$((i + 2))
      ;;
    --screen-dry-run)
      SCREEN_DRY_RUN=1
      i=$((i + 1))
      ;;
    --validate-dry-run)
      VALIDATE_DRY_RUN=1
      i=$((i + 1))
      ;;
    --skip-screen)
      SKIP_SCREEN=1
      i=$((i + 1))
      ;;
    --skip-validate)
      SKIP_VALIDATE=1
      i=$((i + 1))
      ;;
    --solver-model)
      SOLVER_MODEL="${args[$((i + 1))]:-}"
      i=$((i + 2))
      ;;
    --solver-agent)
      SOLVER_AGENT="${args[$((i + 1))]:-}"
      i=$((i + 2))
      ;;
    --solver-timeout)
      SOLVER_TIMEOUT="${args[$((i + 1))]:-}"
      i=$((i + 2))
      ;;
    --validators)
      VALIDATORS="${args[$((i + 1))]:-}"
      i=$((i + 2))
      ;;
    *)
      GEN_ARGS+=("$arg")
      i=$((i + 1))
      ;;
  esac
done

if [[ -z "$REPO" ]]; then
  echo "ERROR: --repo is required." >&2
  exit 1
fi

TOTAL_STEPS=3
if [[ "$SKIP_SCREEN" == "1" ]]; then TOTAL_STEPS=$((TOTAL_STEPS - 1)); fi
if [[ "$SKIP_VALIDATE" == "1" || -z "$SOLVER_MODEL" ]]; then TOTAL_STEPS=$((TOTAL_STEPS - 1)); fi
STEP=1

echo "===== STEP $STEP/$TOTAL_STEPS: GENERATE ====="
python3 -m repogen generate "${GEN_ARGS[@]}"
STEP=$((STEP + 1))

RUN_DIR="$(ls -dt "$OUTPUT_ROOT/$REPO"/run_* 2>/dev/null | head -1 || true)"
if [[ -z "$RUN_DIR" || ! -d "$RUN_DIR/instances" ]]; then
  echo "ERROR: no run directory with instances found under $OUTPUT_ROOT/$REPO" >&2
  exit 1
fi

if [[ "$SKIP_SCREEN" != "1" ]]; then
  echo
  echo "===== STEP $STEP/$TOTAL_STEPS: SCREEN ====="
  SCREEN_ARGS=(--run-dir "$RUN_DIR")
  if [[ "$SCREEN_DRY_RUN" == "1" ]]; then
    SCREEN_ARGS+=(--dry-run)
  fi
  python3 -m repogen screen "${SCREEN_ARGS[@]}"
  STEP=$((STEP + 1))
fi

if [[ "$SKIP_VALIDATE" != "1" && -n "$SOLVER_MODEL" ]]; then
  echo
  echo "===== STEP $STEP/$TOTAL_STEPS: VALIDATE ====="
  VALIDATE_ARGS=(
    --run-dir "$RUN_DIR"
    --validators "$VALIDATORS"
    --solver-agent "$SOLVER_AGENT"
    --solver-model "$SOLVER_MODEL"
    --solver-timeout "$SOLVER_TIMEOUT"
  )
  if [[ "$VALIDATE_DRY_RUN" == "1" ]]; then
    VALIDATE_ARGS+=(--dry-run)
  fi
  python3 -m repogen validate "${VALIDATE_ARGS[@]}"
elif [[ "$SKIP_VALIDATE" != "1" ]]; then
  echo
  echo "NOTE: validation skipped (pass --solver-model <model> to enable it)."
fi

echo
echo "Done."
echo "  Kept instances:       $RUN_DIR/instances"
echo "  Screened out:         $RUN_DIR/excluded_instances"
echo "  Validation discarded: $RUN_DIR/validation_excluded"
echo "  Reports:              $RUN_DIR/screening_report.json, $RUN_DIR/validation_report.json"
