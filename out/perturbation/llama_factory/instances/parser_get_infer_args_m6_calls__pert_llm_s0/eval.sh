#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="parser_get_infer_args_m6_calls__pert_llm_s0"
TEST_ID="llama_factory_qa/parser_get_infer_args_m6_calls__pert_llm_s0/files/testcase.py::TestIndirectInferArgumentCallGraph::test_seeded_chat_model_construction_matrix"
LOG_DIR="$ROOT_DIR/logs/llama_factory_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/llamafactory/hparams/parser.py"
export TRACE_FUNC="read_args,_parse_args,_set_transformers_logging,_verify_model_args,_check_extra_dependencies,_parse_infer_args,get_infer_args,get_train_args,get_eval_args"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python llama_factory_qa/parser_get_infer_args_m6_calls__pert_llm_s0/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/llama_factory_qa/parser_get_infer_args_m6_calls__pert_llm_s0/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
