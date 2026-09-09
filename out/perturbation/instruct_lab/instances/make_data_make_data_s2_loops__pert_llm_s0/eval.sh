#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="make_data_make_data_s2_loops__pert_llm_s0"
TEST_ID="instruct_lab_qa/make_data_make_data_s2_loops__pert_llm_s0/files/testcase.py::TestSimpleTrainDataPreparation::test_preprocessing_via_training_entrypoint"
LOG_DIR="$ROOT_DIR/logs/instruct_lab_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/instructlab/train/lora_mlx/make_data.py"
export TRACE_FUNC="make_data"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python instruct_lab_qa/make_data_make_data_s2_loops__pert_llm_s0/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/instruct_lab_qa/make_data_make_data_s2_loops__pert_llm_s0/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
