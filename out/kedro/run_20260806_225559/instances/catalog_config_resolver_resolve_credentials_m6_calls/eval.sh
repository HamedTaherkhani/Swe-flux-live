#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="catalog_config_resolver_resolve_credentials_m6_calls"
TEST_ID="kedro_qa/catalog_config_resolver_resolve_credentials_m6_calls/files/testcase.py::TestCatalogConfigResolverCallGraph::test_generated_catalog_construction"
LOG_DIR="$ROOT_DIR/logs/kedro_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="kedro/io/catalog_config_resolver.py"
export TRACE_FUNC="__init__,_extract_patterns,_pattern_specificity,_resolve_credentials,_sort_patterns,_unresolve_credentials,_validate_pattern_config,_traverse_config,is_pattern,_resolve_value"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"
export PYTEST_ADDOPTS="--no-cov"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python kedro_qa/catalog_config_resolver_resolve_credentials_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/kedro_qa/catalog_config_resolver_resolve_credentials_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
