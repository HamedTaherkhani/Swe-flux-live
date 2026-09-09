#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="app_handle_exception_s6_calls__pert_llm_s0"
TEST_ID="flask_qa/app_handle_exception_s6_calls__pert_llm_s0/files/testcase.py::TestIndirectExceptionCallGraph::test_generated_requests_exercise_error_pipeline"
LOG_DIR="$ROOT_DIR/logs/flask_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/flask/app.py"
export TRACE_FUNC="handle_exception,ensure_sync,log_exception,finalize_request,make_response,process_response"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python flask_qa/app_handle_exception_s6_calls__pert_llm_s0/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/flask_qa/app_handle_exception_s6_calls__pert_llm_s0/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
