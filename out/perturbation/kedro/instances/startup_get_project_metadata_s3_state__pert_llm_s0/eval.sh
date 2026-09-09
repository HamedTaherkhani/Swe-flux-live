#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="startup_get_project_metadata_s3_state__pert_llm_s0"
TEST_ID="kedro_qa/startup_get_project_metadata_s3_state__pert_llm_s0/files/testcase.py::TestBootstrapMetadataState::test_generated_project_matrix"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/framework/startup.py"
export TRACE_FUNC="_get_project_metadata"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest --no-cov -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/startup_get_project_metadata_s3_state__pert_llm_s0/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/startup_get_project_metadata_s3_state__pert_llm_s0/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
