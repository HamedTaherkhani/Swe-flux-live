#!/usr/bin/env python
"""Trace -> oracle.json for storage_get_prepared_new_trial_s6_calls."""
import argparse
import json
import os
import re
import sys

MOD = "optuna.storages._rdb.storage"
REL_FILE = "optuna/storages/_rdb/storage.py"
TARGET = f"{MOD}.RDBStorage._get_prepared_new_trial"
TRACKED = {
    f"{MOD}.RDBStorage._set_trial_value_without_commit",
    f"{MOD}.RDBStorage._set_trial_param_without_commit",
    f"{MOD}.RDBStorage._set_trial_attr_without_commit",
    f"{MOD}.RDBStorage._set_trial_intermediate_value_without_commit",
}
K = 5  # 1-based invocation of the target

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Run the pytest test "
    "`optuna_qa/storage_get_prepared_new_trial_s6_calls/files/testcase.py::"
    "TestPreparedNewTrial::test_prepare_many_templates` (file "
    "`optuna_qa/storage_get_prepared_new_trial_s6_calls/files/testcase.py`, class "
    "`TestPreparedNewTrial`, the only test method `test_prepare_many_templates`). "
    "The test calls the target function `RDBStorage._get_prepared_new_trial` defined in "
    "`optuna/storages/_rdb/storage.py` (qualname "
    "`optuna.storages._rdb.storage.RDBStorage._get_prepared_new_trial`) several times. "
    "An invocation of the target is one Python function call of it (one `call` event of a "
    "new frame); invocations are numbered 1-based in chronological order over the whole test "
    f"run. Consider invocation number {K} of the target. Report the ordered sequence of calls "
    "made to the following tracked functions, all defined in `optuna/storages/_rdb/storage.py`: "
    "`RDBStorage._set_trial_value_without_commit`, `RDBStorage._set_trial_param_without_commit`, "
    "`RDBStorage._set_trial_attr_without_commit`, and "
    "`RDBStorage._set_trial_intermediate_value_without_commit`. Inclusion rule: a call counts "
    "if it starts (a `call` event of a new frame of one of those four functions) at any time "
    f"while invocation {K} of the target is on the call stack (direct or nested calls both "
    "count; in practice they are direct calls from the target's body). Every call is listed "
    "separately in the chronological order of its `call` event, with repeats kept (no "
    "deduplication). Calls to any other function (e.g. `BaseStorage.check_trial_is_updatable`, "
    "model classmethods, SQLAlchemy, builtins) and the target invocation itself are NOT "
    "included. Answer as JSON `{\"function_call_order\": [{\"file\": str, \"func\": str}, ...]}` "
    "where `file` is the repo-relative path of the callee's source file (forward slashes) and "
    "`func` is the callee's dotted `module.Class.method` name, e.g. "
    "`optuna.storages._rdb.storage.RDBStorage.set_trial_param`."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        fail(f"trace log missing or empty: {args.trace_log}")

    events = []
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if m:
                events.append((m.group("file"), m.group("func"), m.group("event")))

    if not any(f == TARGET and e == "call" for _, f, e in events):
        fail("no call events for target function in trace")

    invocation = 0
    depth = 0  # depth of target frames on the stack
    active = False
    seq = []
    seen_funcs = set()
    for path, func, ev in events:
        if not path.replace("\\", "/").endswith(REL_FILE):
            continue
        seen_funcs.add(func)
        if func == TARGET:
            if ev == "call":
                if depth == 0:
                    invocation += 1
                    active = invocation == K
                depth += 1
            elif ev == "return":
                depth -= 1
                if depth == 0:
                    active = False
            continue
        if active and ev == "call" and func in TRACKED:
            seq.append({"file": REL_FILE, "func": func})

    if invocation < K:
        fail(f"target invoked only {invocation} times; need invocation {K}")
    if not seq:
        fail("empty call sequence for chosen invocation")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    print(f"invocations={invocation} seq_len={len(seq)} traced_funcs={sorted(seen_funcs)}")


if __name__ == "__main__":
    main()
