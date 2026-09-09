#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="protocol_handle_events_s6_calls"
TEST_ID="scrapy_qa/protocol_handle_events_s6_calls/files/testcase.py::ProtocolEventDispatchTest::test_generated_frames_via_data_received"
LOG_DIR="$ROOT_DIR/logs/scrapy_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="scrapy/core/http2/protocol.py"
export TRACE_FUNC="scrapy.core.http2.protocol.H2ClientProtocol._handle_events,scrapy.core.http2.protocol.H2ClientProtocol.connection_terminated,scrapy.core.http2.protocol.H2ClientProtocol.data_received,scrapy.core.http2.protocol.H2ClientProtocol.response_received,scrapy.core.http2.protocol.H2ClientProtocol.settings_acknowledged,scrapy.core.http2.protocol.H2ClientProtocol.stream_ended,scrapy.core.http2.protocol.H2ClientProtocol.stream_reset,scrapy.core.http2.protocol.H2ClientProtocol.window_updated"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python scrapy_qa/protocol_handle_events_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/scrapy_qa/protocol_handle_events_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
