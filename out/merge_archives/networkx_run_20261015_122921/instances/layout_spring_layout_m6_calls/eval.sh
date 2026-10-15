#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="layout_spring_layout_m6_calls"
TEST_ID="networkx_qa/layout_spring_layout_m6_calls/files/testcase.py::TestSpringLayoutCallGraph"
LOG_DIR="$ROOT_DIR/logs/networkx_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="networkx/drawing/layout.py"
# every def in the module (module-level and nested); parser filters by file + AST
export TRACE_FUNC="_cost_FR,_energy_fruchterman_reingold,_fruchterman_reingold,_kamada_kawai_costfn,_kamada_kawai_solve,_process_params,_sparse_fruchterman_reingold,_sparse_spectral,_spectral,arf_layout,bfs_layout,bipartite_layout,circular_layout,estimate_factor,forceatlas2_layout,kamada_kawai_layout,multipartite_layout,planar_layout,random_layout,rescale_layout,rescale_layout_dict,shell_layout,spectral_layout,spiral_layout,spring_layout"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python networkx_qa/layout_spring_layout_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/networkx_qa/layout_spring_layout_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
