#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="serving_make_environ_s6_calls"
TEST_ID="werkzeug_qa/serving_make_environ_s6_calls/files/testcase.py::TestServingRequestCycle::test_sequence_of_requests"
LOG_DIR="$ROOT_DIR/logs/werkzeug_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/werkzeug/"
export TRACE_FUNC="WSGIRequestHandler.make_environ,server_version,_wsgi_encoding_dance,address_string,__getattr__,port_integer,from_header,parse_list_header,unquote_header_value,__init__,__contains__,log,_log,_has_level_handler"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python werkzeug_qa/serving_make_environ_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/werkzeug_qa/serving_make_environ_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
