#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="joint_degree_seq_directed_joint_degree_graph_m3_state"
TEST_ID="networkx_qa/joint_degree_seq_directed_joint_degree_graph_m3_state/files/testcase.py::TestDirectedJointDegreeGraph"
LOG_DIR="$ROOT_DIR/logs/networkx_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="networkx/generators/joint_degree_seq.py"
export TRACE_FUNC="directed_joint_degree_graph"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python networkx_qa/joint_degree_seq_directed_joint_degree_graph_m3_state/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/networkx_qa/joint_degree_seq_directed_joint_degree_graph_m3_state/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
