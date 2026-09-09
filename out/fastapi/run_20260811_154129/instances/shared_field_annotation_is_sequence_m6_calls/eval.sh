#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="shared_field_annotation_is_sequence_m6_calls"
TEST_ID="fastapi_qa/shared_field_annotation_is_sequence_m6_calls/files/testcase.py::RuntimeSequenceGraphTest::test_generated_annotation_matrix"
LOG_DIR="$ROOT_DIR/logs/fastapi_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="fastapi/_compat/shared.py"
export TRACE_FUNC="field_annotation_is_sequence,_annotation_is_sequence,lenient_issubclass,annotation_is_pydantic_v1,is_pydantic_v1_model_class,field_annotation_is_scalar_sequence,field_annotation_is_scalar,field_annotation_is_complex,_annotation_is_complex,is_bytes_sequence_annotation,is_bytes_or_nonable_bytes_annotation,is_uploadfile_sequence_annotation,is_uploadfile_or_nonable_uploadfile_annotation,value_is_sequence"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python fastapi_qa/shared_field_annotation_is_sequence_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/fastapi_qa/shared_field_annotation_is_sequence_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
