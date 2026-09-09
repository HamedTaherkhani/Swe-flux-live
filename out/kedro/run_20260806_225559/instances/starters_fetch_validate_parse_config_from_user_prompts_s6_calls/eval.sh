#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="starters_fetch_validate_parse_config_from_user_prompts_s6_calls"
TEST_ID="kedro_qa/starters_fetch_validate_parse_config_from_user_prompts_s6_calls/files/testcase.py::TestGeneratedInteractiveStarter::test_cli_generated_prompt_flow"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/framework/cli/starters.py"
export TRACE_FUNC="_fetch_validate_parse_config_from_user_prompts,__init__,validate,_parse_tools_input,_validate_range,_validate_tool_selection,_convert_tool_numbers_to_readable_names,_parse_yes_no_to_bool"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest --no-cov -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/starters_fetch_validate_parse_config_from_user_prompts_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/starters_fetch_validate_parse_config_from_user_prompts_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
