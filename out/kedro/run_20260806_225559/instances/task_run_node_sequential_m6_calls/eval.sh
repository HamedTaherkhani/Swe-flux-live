#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="task_run_node_sequential_m6_calls"
TEST_ID="kedro_qa/task_run_node_sequential_m6_calls/files/testcase.py::TestSequentialRunCoverage::test_sequential_pipeline_coverage"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/runner/task.py"
export TRACE_FUNC="__init__,__call__,execute,_run_node_sequential,_run_node_async,_synchronous_dataset_load,_collect_inputs_from_hook,_call_node_run,_run_node_synchronization,_bootstrap_subprocess"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s -o addopts="" -p no:cov "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/task_run_node_sequential_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/task_run_node_sequential_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
