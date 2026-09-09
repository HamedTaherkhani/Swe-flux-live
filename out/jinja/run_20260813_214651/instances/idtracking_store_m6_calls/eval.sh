#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="idtracking_store_m6_calls"
TEST_ID="jinja_qa/idtracking_store_m6_calls/files/testcase.py::IdtrackingStoreM6CallsTest"
LOG_DIR="$ROOT_DIR/logs/jinja_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/jinja2/idtracking.py"
export TRACE_FUNC="__init__,_define_ref,_simple_visit,analyze_node,branch_update,copy,declare_parameter,dump_param_targets,dump_stores,find_load,find_ref,find_symbols,generic_visit,load,ref,store,symbols_for_node,visit_Assign,visit_AssignBlock,visit_Block,visit_CallBlock,visit_FilterBlock,visit_For,visit_FromImport,visit_If,visit_Import,visit_Macro,visit_NSRef,visit_Name,visit_OverlayScope,visit_Scope,visit_With"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python jinja_qa/idtracking_store_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/jinja_qa/idtracking_store_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
