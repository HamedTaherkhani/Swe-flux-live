#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="repr_dispatch_repr_m6_calls"
TEST_ID="werkzeug_qa/repr_dispatch_repr_m6_calls/files/testcase.py::TestDebugReprScenarios"
LOG_DIR="$ROOT_DIR/logs/werkzeug_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/werkzeug/debug/repr.py"
export TRACE_FUNC="debug_repr,dump,__repr__,__call__,_add_subclass_info,_sequence_repr_maker,proxy,__init__,regex_repr,string_repr,dict_repr,object_repr,dispatch_repr,fallback_repr,repr,dump_object,dump_locals,render_object_dump"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python werkzeug_qa/repr_dispatch_repr_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/werkzeug_qa/repr_dispatch_repr_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
