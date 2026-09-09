#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="vllm_infer_vllm_infer_s4_dataflow"
TEST_ID="llama_factory_qa/vllm_infer_vllm_infer_s4_dataflow/files/testcase.py::TestVllmInferDataFlow::test_seeded_cli_entrypoint_multimodal_batches"
LOG_DIR="$ROOT_DIR/logs/llama_factory_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="scripts/vllm_infer.py"
export TRACE_FUNC="vllm_infer"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python llama_factory_qa/vllm_infer_vllm_infer_s4_dataflow/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/llama_factory_qa/vllm_infer_vllm_infer_s4_dataflow/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
