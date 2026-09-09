#!/bin/bash
set -euo pipefail

# Generic per-instance pipeline. Lives inside the container QA dir.
# Stages shared instrumentation + instance files into ROOT_DIR, then runs the
# instance's eval.sh (which traces the test and parses the oracle).

INSTANCE_ID="${1:-}"
ROOT_DIR="${2:-/testbed}"
INSTANCES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_FILES_DIR="$INSTANCES_DIR/shared/files"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE_ID"
INSTANCE_FILES_DIR="$INSTANCE_DIR/files"
INSTANCE_EVAL="$INSTANCE_DIR/eval.sh"

if [[ -z "$INSTANCE_ID" ]]; then
  echo "Usage: $0 <instance_id> [root_dir]"
  echo "Available instances:"
  find "$INSTANCES_DIR" -mindepth 1 -maxdepth 1 -type d -printf "  - %f\n" \
    | grep -vE '^  - (shared|qa_artifacts)$' || true
  exit 1
fi

if [[ ! -d "$INSTANCE_DIR" ]]; then
  echo "ERROR: Instance directory not found: $INSTANCE_DIR"
  exit 1
fi

cd "$ROOT_DIR"

stage_files() {
  local source_dir="$1"
  if [[ ! -d "$source_dir" ]]; then
    return 0
  fi
  while IFS= read -r -d '' src; do
    rel="${src#$source_dir/}"
    dest="$ROOT_DIR/$rel"
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
  done < <(find "$source_dir" -type f -print0)
}

# Shared instrumentation first, then instance-specific files.
stage_files "$SHARED_FILES_DIR"
stage_files "$INSTANCE_FILES_DIR"

if [[ ! -f "$INSTANCE_EVAL" ]]; then
  echo "ERROR: Missing instance eval script: $INSTANCE_EVAL"
  exit 1
fi

chmod +x "$INSTANCE_EVAL"
"$INSTANCE_EVAL" "$ROOT_DIR"
