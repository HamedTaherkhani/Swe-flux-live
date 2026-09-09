#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="llamacpp_convert_to_gguf_convert_llama_to_gguf_s6_calls"
TEST_ID="instruct_lab_qa/llamacpp_convert_to_gguf_convert_llama_to_gguf_s6_calls/files/testcase.py::TestLlamaCppConversionCalls::test_second_seeded_simple_train_conversion"
LOG_DIR="$ROOT_DIR/logs/instruct_lab_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/instructlab/llamacpp/llamacpp_convert_to_gguf.py"
export TRACE_FUNC="convert_llama_to_gguf,convert_model_names,permute_lazy,pick_output_type,convert_to_output_type,GGMLFileType.type_for_tensor,LazyTensor.astype,LazyTensor.validate_conversion_to,default_outfile"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python instruct_lab_qa/llamacpp_convert_to_gguf_convert_llama_to_gguf_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/instruct_lab_qa/llamacpp_convert_to_gguf_convert_llama_to_gguf_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
