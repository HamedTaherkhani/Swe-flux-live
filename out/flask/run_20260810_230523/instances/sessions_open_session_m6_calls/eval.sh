#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="sessions_open_session_m6_calls"
TEST_ID="flask_qa/sessions_open_session_m6_calls/files/testcase.py::TestOpenSessionCallGraph::test_seeded_cookie_matrix"
LOG_DIR="$ROOT_DIR/logs/flask_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="src/flask/sessions.py"
export TRACE_FUNC="flask.sessions.SecureCookieSessionInterface.open_session,flask.sessions.SecureCookieSessionInterface.get_signing_serializer,flask.sessions.SessionInterface.get_cookie_name,flask.sessions.SecureCookieSession.__init__,flask.sessions._lazy_sha1,flask.sessions.SessionInterface.make_null_session"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python flask_qa/sessions_open_session_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/flask_qa/sessions_open_session_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
