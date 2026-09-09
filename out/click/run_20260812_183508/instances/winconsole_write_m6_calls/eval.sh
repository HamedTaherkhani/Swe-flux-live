#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="winconsole_write_m6_calls"
TEST_ID="click_qa/winconsole_write_m6_calls/files/testcase.py::WindowsConsoleWriterCallGraphTest"
LOG_DIR="$ROOT_DIR/logs/click_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/click/_winconsole.py"
export TRACE_FUNC="get_buffer,__init__,isatty,readable,readinto,writable,_get_error_message,write,name,writelines,__getattr__,__repr__,_get_text_stdin,_get_text_stdout,_get_text_stderr,_is_console,_get_windows_console_stream"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python click_qa/winconsole_write_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/click_qa/winconsole_write_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
