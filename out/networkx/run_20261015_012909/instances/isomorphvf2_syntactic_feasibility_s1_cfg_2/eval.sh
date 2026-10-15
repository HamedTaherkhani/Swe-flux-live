#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="isomorphvf2_syntactic_feasibility_s1_cfg_2"
TEST_ID="networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg_2/files/testcase.py::TestSyntacticFeasibilityDirect::test_candidate_pairs_after_partial_mapping"
LOG_DIR="$ROOT_DIR/logs/networkx_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="networkx/algorithms/isomorphism/isomorphvf2.py"
export TRACE_FUNC="GraphMatcher.syntactic_feasibility"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg_2/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/networkx_qa/isomorphvf2_syntactic_feasibility_s1_cfg_2/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
