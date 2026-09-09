#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="omegaconf_config_load_and_merge_dir_config_s2_loops"
TEST_ID="kedro_qa/omegaconf_config_load_and_merge_dir_config_s2_loops/files/testcase.py::TestOmegaConfDirMergeLoops::test_traced_run"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/config/omegaconf_config.py"
export TRACE_FUNC="load_and_merge_dir_config"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s -o addopts="" -p no:cov "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/omegaconf_config_load_and_merge_dir_config_s2_loops/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/omegaconf_config_load_and_merge_dir_config_s2_loops/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
