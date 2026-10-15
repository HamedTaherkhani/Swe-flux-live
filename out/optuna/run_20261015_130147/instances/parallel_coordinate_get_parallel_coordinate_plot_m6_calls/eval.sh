#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="parallel_coordinate_get_parallel_coordinate_plot_m6_calls"
TEST_ID="optuna_qa/parallel_coordinate_get_parallel_coordinate_plot_m6_calls/files/testcase.py::TestParallelCoordinateCallGraph"
LOG_DIR="$ROOT_DIR/logs/optuna_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="optuna/visualization/_parallel_coordinate.py"
export TRACE_FUNC="plot_parallel_coordinate,_get_parallel_coordinate_plot,_get_feasibility_legend_traces,_get_parallel_coordinate_info,_build_numerical_dimension,_get_feasibility,_get_missing_value,_normalize_dimension,_get_line_colors,_sample_colorscale,_get_color_range,_format_dimension_value,_get_axis_annotations,_truncate_label"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python optuna_qa/parallel_coordinate_get_parallel_coordinate_plot_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/optuna_qa/parallel_coordinate_get_parallel_coordinate_plot_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
