#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="tree_matcher_match_tree_s6_calls"
TEST_ID="lark_qa/tree_matcher_match_tree_s6_calls/files/testcase.py::TestTreeMatcherCallStructure::test_seeded_mixed_segment_batches"
LOG_DIR="$ROOT_DIR/logs/lark_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="lark/tree_matcher.py"
export TRACE_FUNC="TreeMatcher.match_tree,parse_rulename,_best_rules_from_group,_best_from_group,_best_rules_from_group.<locals>.<lambda>,TreeMatcher.match_tree.<locals>.<dictcomp>,ChildrenLexer.__init__,ChildrenLexer.lex,_match,_MakeTreeMatch.__call__"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python lark_qa/tree_matcher_match_tree_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/lark_qa/tree_matcher_match_tree_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
