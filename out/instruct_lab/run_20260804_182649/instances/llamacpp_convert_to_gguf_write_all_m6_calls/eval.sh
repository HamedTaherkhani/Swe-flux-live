#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="llamacpp_convert_to_gguf_write_all_m6_calls"
TEST_ID="instruct_lab_qa/llamacpp_convert_to_gguf_write_all_m6_calls/files/testcase.py::TestLlamaCppConversionCallGraph::test_programmatic_model_conversion"
LOG_DIR="$ROOT_DIR/logs/instruct_lab_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/instructlab/llamacpp/llamacpp_convert_to_gguf.py"
export TRACE_FUNC="convert_llama_to_gguf,check_vocab_size,bounded_parallel_map,OutputFile.__init__,OutputFile.write_all,OutputFile.write_vocab_only,OutputFile.add_meta_arch,OutputFile.add_meta_vocab,OutputFile.handle_tokenizer_model,OutputFile.extract_vocabulary_from_model,OutputFile.add_meta_special_vocab,OutputFile.add_tensor_info,OutputFile.write_meta,OutputFile.write_tensor_info,OutputFile.do_item,OutputFile.maybe_do_quantize,OutputFile.close,BpeVocab.all_tokens,BpeVocab.bpe_tokens,BpeVocab.added_tokens,SentencePieceVocab.all_tokens,Q8_0QuantizedDataType.quantize"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python instruct_lab_qa/llamacpp_convert_to_gguf_write_all_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/instruct_lab_qa/llamacpp_convert_to_gguf_write_all_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
