#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="python_aggregate_s6_calls"
TEST_ID="sqlglot_qa/python_aggregate_s6_calls/files/testcase.py::TestPythonAggregateCalls::test_seeded_grouped_aggregation"
LOG_DIR="$ROOT_DIR/logs/sqlglot_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="sqlglot/executor/python.py"
export TRACE_FUNC="PythonExecutor.aggregate,PythonExecutor.generate_tuple,PythonExecutor.generate,PythonExecutor.table,PythonExecutor.context,PythonExecutor.aggregate.<locals>.add_row,PythonExecutor.scan,PythonExecutor._project_and_filter"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python sqlglot_qa/python_aggregate_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/sqlglot_qa/python_aggregate_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
