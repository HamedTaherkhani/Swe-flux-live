#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="engine_open_spider_async_s6_calls__pert_llm_s0"
TEST_ID="scrapy_qa/engine_open_spider_async_s6_calls__pert_llm_s0/files/testcase.py::TestEngineOpenSpiderCallFlow::test_dynamic_signal_dispatch"
LOG_DIR="$ROOT_DIR/logs/scrapy_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="scrapy/core/engine.py"
export TRACE_FUNC="scrapy.core.engine.ExecutionEngine.open_spider_async,scrapy.core.engine.ExecutionEngine.needs_backout,scrapy.core.engine.ExecutionEngine.pause,scrapy.core.engine.ExecutionEngine.spider_is_idle,scrapy.core.engine.ExecutionEngine.unpause,scrapy.core.engine._Slot.__init__"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python scrapy_qa/engine_open_spider_async_s6_calls__pert_llm_s0/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/scrapy_qa/engine_open_spider_async_s6_calls__pert_llm_s0/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
