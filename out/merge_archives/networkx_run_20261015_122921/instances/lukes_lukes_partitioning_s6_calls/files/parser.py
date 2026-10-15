#!/usr/bin/env python
"""Trace -> oracle.json for lukes_lukes_partitioning_s6_calls."""

import argparse
import json
import re
import sys

REL_FILE = "networkx/algorithms/community/lukes.py"
MOD = "networkx.algorithms.community.lukes"
TARGET = f"{MOD}.lukes_partitioning"
TRACKED = [
    f"{TARGET}.<locals>._a_parent_of_leaves_only",
    f"{TARGET}.<locals>._concatenate_or_merge",
    f"{TARGET}.<locals>._weight_of_cluster",
    f"{TARGET}.<locals>._value_of_cluster",
]
EVENT_RE = re.compile(r"^\S+ \S+ (\S+):(\d+) (\S+) event=(\w+)")

QUESTION = (
    "Consider the pytest test "
    "`networkx_qa/lukes_lukes_partitioning_s6_calls/files/testcase.py::"
    "TestLukesSeededTree::test_seeded_directed_tree` (test class "
    "`TestLukesSeededTree`, single test method `test_seeded_directed_tree`). "
    "It calls the target function `networkx.algorithms.community.lukes.lukes_partitioning` "
    "(defined in `networkx/algorithms/community/lukes.py`) exactly once; consider that "
    "single (1st, 1-based) invocation, i.e. the execution of the body of "
    "`lukes_partitioning` in lukes.py from when its frame is entered until it returns.\n\n"
    "Tracked functions (exactly these four nested helper functions defined inside "
    "`lukes_partitioning`, identified by their dotted `module.qualname`):\n"
    "- `networkx.algorithms.community.lukes.lukes_partitioning.<locals>._a_parent_of_leaves_only`\n"
    "- `networkx.algorithms.community.lukes.lukes_partitioning.<locals>._concatenate_or_merge`\n"
    "- `networkx.algorithms.community.lukes.lukes_partitioning.<locals>._weight_of_cluster`\n"
    "- `networkx.algorithms.community.lukes.lukes_partitioning.<locals>._value_of_cluster`\n\n"
    "Report the chronological sequence of calls to the tracked functions that occur while "
    "that invocation of `lukes_partitioning` is on the stack. A \"call\" is the moment a "
    "new Python frame for the tracked function's own body (the code in lukes.py) is entered, "
    "i.e. a Python `call` trace event for that code object, ordered by when it happens. "
    "Calls count whether made directly by `lukes_partitioning`'s frame or transitively from "
    "nested callees (e.g. a `_weight_of_cluster` call made from inside "
    "`_concatenate_or_merge` counts). Important: `_weight_of_cluster` and "
    "`_value_of_cluster` are wrapped by `functools.lru_cache`; a cache hit does NOT execute "
    "the function body and therefore is NOT counted - only cache misses (actual body "
    "executions) appear. Decorator/wrapper frames (`not_implemented_for` / argmap, "
    "lru_cache internals), lambdas, comprehensions, generators (`_leaves`, `_split_n_from`), "
    "`_pivot`, `_value_of_partition`, networkx library functions and builtins are NOT tracked "
    "and never appear. Every call is listed separately (no deduplication, repeated calls appear "
    "as many times as they occur).\n\n"
    "Answer format: a JSON object `{\"function_call_order\": [{\"file\": str, \"func\": str}, ...]}` "
    "with one element per call in chronological order. `file` is the repo-relative path of the "
    "file defining the function (always `networkx/algorithms/community/lukes.py` here) and "
    "`func` is the full dotted `module.qualname` exactly as listed above, e.g. "
    "`networkx.algorithms.community.lukes.lukes_partitioning.<locals>._leaves` for the "
    "(untracked) `_leaves` helper."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log missing: {args.trace_log}")
    if not lines:
        sys.exit("ERROR: trace log is empty")

    events = []
    for ln in lines:
        m = EVENT_RE.match(ln)
        if m:
            events.append((m.group(1), int(m.group(2)), m.group(3), m.group(4)))

    target_events = [e for e in events if e[2] == TARGET]
    if not target_events:
        sys.exit("ERROR: zero trace events for target function")

    target_calls = [i for i, e in enumerate(events) if e[2] == TARGET and e[3] == "call"]
    if len(target_calls) != 1:
        sys.exit(f"ERROR: expected exactly 1 target invocation, got {len(target_calls)}")

    seq = []
    depth = 0
    started = False
    for f, _lineno, func, ev in events:
        if func == TARGET:
            if ev == "call":
                depth += 1
                started = True
            elif ev == "return":
                depth -= 1
                if started and depth == 0:
                    break
            continue
        if depth > 0 and ev == "call" and func in TRACKED:
            if not f.replace("\\", "/").endswith(REL_FILE):
                sys.exit(f"ERROR: unexpected file for {func}: {f}")
            seq.append({"file": REL_FILE, "func": func})
    else:
        sys.exit("ERROR: target invocation never returned")

    seen = {d["func"] for d in seq}
    missing = [t for t in TRACKED if t not in seen]
    if missing:
        sys.exit(f"ERROR: tracked functions never captured: {missing}")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"function_call_order length: {len(seq)}")


if __name__ == "__main__":
    main()
