#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="genspider_run_s6_calls"
TEST_ID="scrapy_qa/genspider_run_s6_calls/files/testcase.py::TestGenspiderRunCallStructure::test_seeded_command_modes"
LOG_DIR="$ROOT_DIR/logs/scrapy_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="scrapy/commands/genspider.py"
export TRACE_FUNC="scrapy.commands.genspider.Command.run,scrapy.commands.genspider.Command._find_template,scrapy.commands.genspider.Command._generate_template_variables,scrapy.commands.genspider.Command._genspider,scrapy.commands.genspider.Command._list_templates,scrapy.commands.genspider.Command._spider_exists,scrapy.commands.genspider.extract_domain,scrapy.commands.genspider.sanitize_module_name,scrapy.commands.genspider.verify_url_scheme"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python scrapy_qa/genspider_run_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/scrapy_qa/genspider_run_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"

