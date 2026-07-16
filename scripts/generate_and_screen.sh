#!/usr/bin/env bash
set -euo pipefail

# Generate instances for a repo, then screen them (runtime exclusion rules).
# All arguments are forwarded to `repogen generate`; the newest run directory
# is then screened. Example:
#
#   ./scripts/generate_and_screen.sh \
#     --repo faker_qa --agent cursor --model gpt-5.3-codex-high --num-instances 40
#
# Extra flags:
#   --screen-dry-run   report screening verdicts without moving instances

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

REPO=""
OUTPUT_ROOT="$PROJECT_ROOT/out"
SCREEN_DRY_RUN=0
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

echo "===== STEP 1/2: GENERATE ====="
python3 -m repogen generate "${GEN_ARGS[@]}"

RUN_DIR="$(ls -dt "$OUTPUT_ROOT/$REPO"/run_* 2>/dev/null | head -1 || true)"
if [[ -z "$RUN_DIR" || ! -d "$RUN_DIR/instances" ]]; then
  echo "ERROR: no run directory with instances found under $OUTPUT_ROOT/$REPO" >&2
  exit 1
fi

echo
echo "===== STEP 2/2: SCREEN ====="
SCREEN_ARGS=(--run-dir "$RUN_DIR")
if [[ "$SCREEN_DRY_RUN" == "1" ]]; then
  SCREEN_ARGS+=(--dry-run)
fi
python3 -m repogen screen "${SCREEN_ARGS[@]}"

echo
echo "Done."
echo "  Kept instances:     $RUN_DIR/instances"
echo "  Excluded instances: $RUN_DIR/excluded_instances"
echo "  Screening report:   $RUN_DIR/screening_report.json"
