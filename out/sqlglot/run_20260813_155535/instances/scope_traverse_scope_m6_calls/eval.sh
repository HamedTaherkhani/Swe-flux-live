#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="scope_traverse_scope_m6_calls"
TEST_ID="sqlglot_qa/scope_traverse_scope_m6_calls/files/testcase.py::TestScopeTraversalCalls"
LOG_DIR="$ROOT_DIR/logs/sqlglot_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="sqlglot/optimizer/scope.py"
export TRACE_FUNC="traverse_scope,build_scope,_traverse_scope,_traverse_select,_traverse_union,_traverse_ctes,_is_derived_table,_is_from_or_join,_traverse_tables,_traverse_subqueries,_traverse_udtfs,walk_in_scope,find_all_in_scope,find_in_scope,_get_source_alias,__init__,clear_column_cache,clear_cache,branch,_collect,_ensure_collected,walk,find,find_all,replace,tables,ctes,derived_tables,udtfs,subqueries,scans_all_subscope_columns,stars,column_index,columns,table_columns,selected_sources,references,external_columns,local_columns,unqualified_columns,join_hints,pivots,semi_or_anti_join_tables,source_columns,is_subquery,is_derived_table,is_union,is_cte,is_root,is_udtf,is_correlated_subquery,rename_source,add_source,remove_source,__repr__,traverse,ref_count"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python sqlglot_qa/scope_traverse_scope_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/sqlglot_qa/scope_traverse_scope_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
