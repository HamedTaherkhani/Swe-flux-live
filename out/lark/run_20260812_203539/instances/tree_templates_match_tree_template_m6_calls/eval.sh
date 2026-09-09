#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="tree_templates_match_tree_template_m6_calls"
TEST_ID="lark_qa/tree_templates_match_tree_template_m6_calls/files/testcase.py::TestTemplateSearchDynamics"
LOG_DIR="$ROOT_DIR/logs/lark_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="lark/tree_templates.py"
export TRACE_FUNC="lark.tree_templates.TemplateConf.__init__,lark.tree_templates.TemplateConf.test_var,lark.tree_templates.TemplateConf._get_tree,lark.tree_templates.TemplateConf.__call__,lark.tree_templates.TemplateConf._match_tree_template,lark.tree_templates._ReplaceVars.__init__,lark.tree_templates._ReplaceVars.__default__,lark.tree_templates.Template.__init__,lark.tree_templates.Template.match,lark.tree_templates.Template.search,lark.tree_templates.Template.apply_vars,lark.tree_templates.translate,lark.tree_templates.TemplateTranslator.__init__,lark.tree_templates.TemplateTranslator.translate,lark.tree_templates._get_template_name"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python lark_qa/tree_templates_match_tree_template_m6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/lark_qa/tree_templates_match_tree_template_m6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
