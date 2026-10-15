#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="tree_get_marginalized_statistics_m6_calls"
TEST_ID="optuna_qa/tree_get_marginalized_statistics_m6_calls/files/testcase.py::TestFanovaForestMarginals"
LOG_DIR="$ROOT_DIR/logs/optuna_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="optuna/importance/_fanova/_tree.py"
export TRACE_FUNC="__init__,variance,get_marginal_variance,_get_marginalized_statistics,_precompute_statistics,_precompute_split_midpoints_and_sizes,_compute_features_split_values,_precompute_subtree_active_features,_n_features,_n_nodes,_is_node_leaf,_get_node_left_child,_get_node_right_child,_get_node_children,_get_node_value,_get_node_split_threshold,_get_node_split_feature,_get_node_left_child_subspaces,_get_node_right_child_subspaces,_get_node_children_subspaces,_get_cardinality,_get_cardinality_batched,_get_subspaces"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python optuna_qa/tree_get_marginalized_statistics_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/optuna_qa/tree_get_marginalized_statistics_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
