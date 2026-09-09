#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="core_convert_m6_calls"
TEST_ID="sqlglot_qa/core_convert_m6_calls/files/testcase.py::TestConvertCallGraph"
LOG_DIR="$ROOT_DIR/logs/sqlglot_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="sqlglot/expressions/core.py"
export TRACE_FUNC="_apply_builder,_apply_child_list_builder,_apply_conjunction_builder,_apply_list_builder,_apply_set_operation,_combine,_is_wrong_expression,_lazy_unnest,_to_s,_wrap,alias_,and_,column,condition,convert,maybe_copy,maybe_parse,not_,or_,paren,to_identifier,xor"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python sqlglot_qa/core_convert_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/sqlglot_qa/core_convert_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
