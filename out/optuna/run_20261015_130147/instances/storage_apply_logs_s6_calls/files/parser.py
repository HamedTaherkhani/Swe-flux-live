"""Derive the S6 (inter-procedural call order) oracle for JournalStorageReplayResult.apply_logs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys


REPO_FILE = "optuna/storages/journal/_storage.py"
MODULE = "optuna.storages.journal._storage"
CLS = f"{MODULE}.JournalStorageReplayResult"
TARGET = f"{CLS}.apply_logs"
TARGET_INVOCATION = 2
TRACKED_NAMES = [
    "_apply_create_study",
    "_apply_delete_study",
    "_apply_set_study_user_attr",
    "_apply_set_study_system_attr",
    "_apply_create_trial",
    "_apply_set_trial_param",
    "_apply_set_trial_state_values",
    "_apply_set_trial_intermediate_value",
    "_apply_set_trial_user_attr",
    "_apply_set_trial_system_attr",
    "_study_exists",
    "_trial_exists_and_updatable",
    "_is_issued_by_this_worker",
    "worker_id",
]
TRACKED = {f"{CLS}.{n}" for n in TRACKED_NAMES}
TEST_FILE = "optuna_qa/storage_apply_logs_s6_calls/files/testcase.py"
TEST_ID = f"{TEST_FILE}::TestJournalReplayApplyLogs::test_replay_three_batches"

EVENT_RE = re.compile(r" (?P<file>/\S+\.py):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

_tracked_list = "\n".join(
    f"  {i}. `{CLS}.{n}`" + (" (the getter of the `worker_id` property)" if n == "worker_id" else "")
    for i, n in enumerate(TRACKED_NAMES, 1)
)

QUESTION = f"""\
Consider the pytest test `{TEST_ID}` (file `{TEST_FILE}`, class `TestJournalReplayApplyLogs`, single test method `test_replay_three_batches`), run once from the repository root.

The target function is `JournalStorageReplayResult.apply_logs` in `{REPO_FILE}` (qualname `{TARGET}`). The test calls it directly three times, once per log batch. An "invocation" of the target is one call of `apply_logs`, numbered 1-based in chronological order during the test run. This question is about invocation {TARGET_INVOCATION} only (the call that replays `batch2`).

Tracked functions (exactly these {len(TRACKED_NAMES)}, all methods of `JournalStorageReplayResult` in `{REPO_FILE}`; any other function, method, builtin, list/dict comprehension frame, lambda, enum/property machinery, or code in other files -- e.g. `json_to_distribution`, `check_distribution_compatibility`, `copy.copy`, `TrialState.is_finished`, `FrozenTrial` methods -- is NOT tracked and must not appear):
{_tracked_list}

A "call" is the start of a new Python frame executing one of these functions (each actual invocation counted once; none are generators, so there are no resumptions). Every evaluation of the `self.worker_id` property counts as one call of the `worker_id` getter. Inclusion rule: record every call of a tracked function that starts while invocation {TARGET_INVOCATION} of the target is on the call stack -- transitive/nested calls count too (e.g. a tracked helper called from inside another tracked helper is included), not only calls made directly from the target's own frame. Do NOT include the call of the target `apply_logs` itself. Calls during invocations 1 and 3 are excluded. Repeated calls are each listed separately (no deduplication), in chronological order of when each call starts.

Report this as `function_call_order`: a JSON list of objects `{{"file": ..., "func": ...}}` in chronological order, where `file` is the repo-relative path of the defining file (always `{REPO_FILE}` here) and `func` is the dotted `module.qualname` of the called function, e.g. `{CLS}.get_trial` (no `<locals>`, no argument lists, no parentheses)."""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        fail("trace log is empty")

    events = []
    for raw in lines:
        m = EVENT_RE.search(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(REPO_FILE):
            continue
        events.append((m.group("func"), m.group("event")))

    n_calls = sum(1 for f, e in events if f == TARGET and e == "call")
    if n_calls == 0:
        fail("no call events for the target function in the trace")
    if n_calls < TARGET_INVOCATION:
        fail(f"only {n_calls} target invocations; need {TARGET_INVOCATION}")

    invocation = 0
    depth = 0
    order = []
    for func, event in events:
        if func == TARGET and event == "call":
            if depth == 0:
                invocation += 1
            depth += 1
            continue
        if func == TARGET and event == "return":
            depth -= 1
            if depth < 0:
                fail("unbalanced target return event")
            continue
        if event == "call" and func in TRACKED and depth > 0 and invocation == TARGET_INVOCATION:
            order.append({"file": REPO_FILE, "func": func})

    if depth != 0:
        fail("target invocation never returned")
    if len(order) < 10:
        fail("suspiciously short call order")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": order},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"target invocations: {n_calls}; call order length: {len(order)}")


if __name__ == "__main__":
    main()
