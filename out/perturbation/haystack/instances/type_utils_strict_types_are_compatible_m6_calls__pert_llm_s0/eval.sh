#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="type_utils_strict_types_are_compatible_m6_calls__pert_llm_s0"
TEST_ID="haystack_qa/type_utils_strict_types_are_compatible_m6_calls__pert_llm_s0/files/testcase.py::TestStrictTypeUtilsInvocationCounts"
LOG_DIR="$ROOT_DIR/logs/haystack_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="haystack/core/type_utils.py"
export TRACE_FUNC="_types_are_compatible,_safe_get_origin,_strict_types_are_compatible,_check_callable_compatibility,_type_name"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python haystack_qa/type_utils_strict_types_are_compatible_m6_calls__pert_llm_s0/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/haystack_qa/type_utils_strict_types_are_compatible_m6_calls__pert_llm_s0/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
