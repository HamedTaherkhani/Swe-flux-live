#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="blueprints_merge_blueprint_funcs_s6_calls"
TEST_ID="flask_qa/blueprints_merge_blueprint_funcs_s6_calls/files/testcase.py::TestBlueprintMergeRuntime::test_repeated_registration_call_path"
LOG_DIR="$ROOT_DIR/logs/flask_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/flask/sansio/blueprints.py"
export TRACE_FUNC="flask.sansio.blueprints.Blueprint._merge_blueprint_funcs,flask.sansio.blueprints.Blueprint._merge_blueprint_funcs.<locals>.extend,flask.sansio.blueprints.Blueprint._merge_blueprint_funcs.<locals>.<dictcomp>"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python flask_qa/blueprints_merge_blueprint_funcs_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/flask_qa/blueprints_merge_blueprint_funcs_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
