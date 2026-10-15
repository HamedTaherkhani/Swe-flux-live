#!/bin/bash
set -euo pipefail

ROOT_DIR="${1:-/testbed}"
INSTANCE_ID="storage_apply_logs_s6_calls"
TEST_ID="optuna_qa/storage_apply_logs_s6_calls/files/testcase.py::TestJournalReplayApplyLogs::test_replay_three_batches"
LOG_DIR="$ROOT_DIR/logs/optuna_qa/$INSTANCE_ID"

TRACE_LOG="$LOG_DIR/trace.log"
PYTEST_LOG="$LOG_DIR/pytest.log"
ORACLE_LOG="$LOG_DIR/oracle.log"
ORACLE_JSON="$LOG_DIR/oracle.json"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

export TRACE_ON="1"
export TRACE_FILE="optuna/storages/journal/_storage.py"
export TRACE_FUNC="JournalStorageReplayResult.apply_logs,JournalStorageReplayResult._apply_create_study,JournalStorageReplayResult._apply_delete_study,JournalStorageReplayResult._apply_set_study_user_attr,JournalStorageReplayResult._apply_set_study_system_attr,JournalStorageReplayResult._apply_create_trial,JournalStorageReplayResult._apply_set_trial_param,JournalStorageReplayResult._apply_set_trial_state_values,JournalStorageReplayResult._apply_set_trial_intermediate_value,JournalStorageReplayResult._apply_set_trial_user_attr,JournalStorageReplayResult._apply_set_trial_system_attr,JournalStorageReplayResult._study_exists,JournalStorageReplayResult._trial_exists_and_updatable,JournalStorageReplayResult._is_issued_by_this_worker,JournalStorageReplayResult.worker_id"
export TRACE_EVENTS="line,call,return,exception"
export TRACE_LOG_ALL_LINES="1"
export TRACE_OUT="$TRACE_LOG"

rm -f "$TRACE_LOG" "$PYTEST_LOG" "$ORACLE_LOG" "$ORACLE_JSON"

pytest -rA -s "$TEST_ID" 2>&1 | tee "$PYTEST_LOG"

python optuna_qa/storage_apply_logs_s6_calls/files/parser.py \
  --trace-log "$TRACE_LOG" \
  --out "$ORACLE_JSON" | tee "$ORACLE_LOG"

cp "$ORACLE_JSON" "$ROOT_DIR/optuna_qa/storage_apply_logs_s6_calls/oracle.json"

echo "Instance:   $INSTANCE_ID"
echo "Oracle json: $ORACLE_JSON"
