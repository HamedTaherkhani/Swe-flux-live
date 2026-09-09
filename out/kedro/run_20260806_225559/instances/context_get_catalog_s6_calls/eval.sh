#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="context_get_catalog_s6_calls"
TEST_ID="kedro_qa/context_get_catalog_s6_calls/files/testcase.py::TestCatalogCallChain::test_tracked_call_order"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/framework/context/context.py"
export TRACE_FUNC="_get_catalog,params,_get_config_credentials,_get_parameters,_add_param_to_params_dict,_convert_paths_to_absolute_posix,_is_relative_path,_update_nested_dict,_validate_transcoded_datasets,compose_classes"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s -o addopts="" -p no:cov "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/context_get_catalog_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/context_get_catalog_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
