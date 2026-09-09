#!/bin/bash
set -euo pipefail

# Run all QA instances from host (outside Docker), one by one.
# This script lives in the QA directory. Oracles and logs land under ./qa_artifacts.

QA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$QA_DIR/run_qa_fromhost.sh"
ARTIFACTS_DIR="$QA_DIR/qa_artifacts"

if [[ ! -x "$RUNNER" ]]; then
  echo "ERROR: Missing executable runner: $RUNNER"
  echo "Run: chmod +x $RUNNER"
  exit 1
fi

INSTANCES=()
while IFS= read -r d; do
  name="$(basename "$d")"
  case "$name" in
    shared|qa_artifacts)
      continue
      ;;
    *)
      INSTANCES+=("$name")
      ;;
  esac
done < <(find "$QA_DIR" -mindepth 1 -maxdepth 1 -type d | sort)

if [[ ${#INSTANCES[@]} -eq 0 ]]; then
  echo "No QA instances found in: $QA_DIR"
  exit 1
fi

echo "Found ${#INSTANCES[@]} QA instances:"
for inst in "${INSTANCES[@]}"; do
  echo "  - $inst"
done

for inst in "${INSTANCES[@]}"; do
  echo
  echo "===== RUNNING INSTANCE: $inst ====="
  HOST_QA_DIR="$QA_DIR" HOST_OUTPUT_DIR="$ARTIFACTS_DIR" "$RUNNER" "$inst"
done

echo
echo "All QA instances completed."
echo "Artifacts root: $ARTIFACTS_DIR"
