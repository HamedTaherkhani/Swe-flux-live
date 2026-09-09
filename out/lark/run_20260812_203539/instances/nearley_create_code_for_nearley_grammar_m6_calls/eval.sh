#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="nearley_create_code_for_nearley_grammar_m6_calls"
TEST_ID="lark_qa/nearley_create_code_for_nearley_grammar_m6_calls/files/testcase.py::TestNearleyCodeGenerationDynamics"
LOG_DIR="$ROOT_DIR/logs/lark_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="lark/tools/nearley.py"
export TRACE_FUNC="lark.tools.nearley._get_rulename,lark.tools.nearley.NearleyToLark.__init__,lark.tools.nearley.NearleyToLark._new_function,lark.tools.nearley.NearleyToLark._extra_rule,lark.tools.nearley.NearleyToLark.rule,lark.tools.nearley.NearleyToLark.ruledef,lark.tools.nearley.NearleyToLark.expr,lark.tools.nearley.NearleyToLark.regexp,lark.tools.nearley.NearleyToLark.null,lark.tools.nearley.NearleyToLark.string,lark.tools.nearley.NearleyToLark.expansion,lark.tools.nearley.NearleyToLark.expansions,lark.tools.nearley.NearleyToLark.start,lark.tools.nearley._nearley_to_lark,lark.tools.nearley.create_code_for_nearley_grammar,lark.tools.nearley.main,lark.tools.nearley.get_arg_parser"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python lark_qa/nearley_create_code_for_nearley_grammar_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/lark_qa/nearley_create_code_for_nearley_grammar_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
