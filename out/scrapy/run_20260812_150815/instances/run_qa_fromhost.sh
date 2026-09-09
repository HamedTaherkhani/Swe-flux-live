#!/bin/bash
set -euo pipefail

# Run on host machine (outside Docker).
# It starts a fresh container, stages qa scripts/files, runs one instance,
# copies back instance-specific artifacts, and removes the container.

INSTANCE_ID="${1:-}"
IMAGE="${IMAGE:-repolaunch/repogen:scrapy__scrapy-74f062f_linux}"
CONTAINER_NAME="${CONTAINER_NAME:-qa-pipeline-runner-scrapy_qa}"
_RUNNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_QA_DIR="${HOST_QA_DIR:-$_RUNNER_DIR}"
HOST_OUTPUT_DIR="${HOST_OUTPUT_DIR:-$HOST_QA_DIR/qa_artifacts}"
CONTAINER_REPO_DIR="/testbed"
CONTAINER_QA_DIR="$CONTAINER_REPO_DIR/scrapy_qa"

HOST_PIPELINE_SCRIPT="$HOST_QA_DIR/qa_pipeline.sh"

if [[ -z "$INSTANCE_ID" ]]; then
  echo "Usage: $0 <instance_id>"
  echo "Run this script from the QA directory or set HOST_QA_DIR to it."
  echo "Available instances:"
  find "$HOST_QA_DIR" -mindepth 1 -maxdepth 1 -type d -printf "  - %f\n" \
    | grep -vE '^  - (shared|qa_artifacts)$' || true
  exit 1
fi

echo "Instance:        $INSTANCE_ID"
echo "Image:           $IMAGE"
echo "Container name:  $CONTAINER_NAME"
echo "Host qa dir:     $HOST_QA_DIR"
echo "Host output dir: $HOST_OUTPUT_DIR"

if [[ ! -f "$HOST_PIPELINE_SCRIPT" ]]; then
  echo "ERROR: Missing pipeline script: $HOST_PIPELINE_SCRIPT"
  exit 1
fi
if [[ ! -d "$HOST_QA_DIR/shared" ]]; then
  echo "ERROR: Missing shared directory: $HOST_QA_DIR/shared"
  exit 1
fi
if [[ ! -d "$HOST_QA_DIR/$INSTANCE_ID" ]]; then
  echo "ERROR: Missing instance directory: $HOST_QA_DIR/$INSTANCE_ID"
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Image not found locally. Pulling: $IMAGE"
  docker pull "$IMAGE"
else
  echo "Image already available locally."
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

docker run -d \
  --name "$CONTAINER_NAME" \
  -w "$CONTAINER_REPO_DIR" \
  "$IMAGE" \
  tail -f /dev/null

docker exec "$CONTAINER_NAME" bash -lc "mkdir -p $CONTAINER_QA_DIR"
docker cp "$HOST_QA_DIR/." "$CONTAINER_NAME:$CONTAINER_QA_DIR"

docker exec "$CONTAINER_NAME" bash -lc "chmod +x $CONTAINER_QA_DIR/qa_pipeline.sh && $CONTAINER_QA_DIR/qa_pipeline.sh $INSTANCE_ID $CONTAINER_REPO_DIR"

mkdir -p "$HOST_OUTPUT_DIR"
INSTANCE_HOST_OUT="$HOST_OUTPUT_DIR/$INSTANCE_ID"
mkdir -p "$INSTANCE_HOST_OUT"
docker cp "$CONTAINER_NAME:$CONTAINER_REPO_DIR/logs/scrapy_qa/$INSTANCE_ID/." "$INSTANCE_HOST_OUT/"

echo "Pipeline completed in container: $CONTAINER_NAME"
echo "Copied artifacts to: $INSTANCE_HOST_OUT"
echo "Oracle file: $INSTANCE_HOST_OUT/oracle.json"

docker rm -f "$CONTAINER_NAME" >/dev/null
echo "Container removed: $CONTAINER_NAME"
