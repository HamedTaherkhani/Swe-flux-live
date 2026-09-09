#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="ipython_load_node_m6_calls"
TEST_ID="kedro_qa/ipython_load_node_m6_calls/files/testcase.py::TestIPythonLoadNodeCallGraph::test_generated_node_magic_calls"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/ipython/__init__.py"
export TRACE_FUNC="_find_var_positional_arg,input_params_dict,_create_cell_with_text,_find_node,_format_node_inputs_text,_get_node_bound_arguments,_guess_run_environment,_load_node,_prepare_function_body,_prepare_function_call,_prepare_imports,_prepare_node_inputs,_print_cells,load_ipython_extension,magic_load_node"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest --no-cov -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/ipython_load_node_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/ipython_load_node_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
