#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="fields_deserialize_m6_calls_4"
TEST_ID="marshmallow_qa/fields_deserialize_m6_calls_4/files/testcase.py::TestAwareDateTimeDeserialize"
LOG_DIR="$ROOT_DIR/logs/marshmallow_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/marshmallow/"
export TRACE_FUNC="__init__,_bind_to_schema,_serialize,_deserialize,_make_object_from_format,is_generator,is_iterable_but_not_string,is_sequence_but_not_string,is_collection,is_aware,from_timestamp,from_timestamp_ms,timestamp,timestamp_ms,ensure_text_type,pluck,get_value,_get_value_for_key,set_value,callable_or_raise,timedelta_to_microseconds"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python marshmallow_qa/fields_deserialize_m6_calls_4/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/marshmallow_qa/fields_deserialize_m6_calls_4/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
