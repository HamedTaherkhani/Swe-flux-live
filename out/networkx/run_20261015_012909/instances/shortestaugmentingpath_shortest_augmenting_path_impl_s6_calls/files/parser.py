#!/usr/bin/env python
"""Trace -> oracle.json for shortestaugmentingpath_shortest_augmenting_path_impl_s6_calls."""

import argparse
import json
import re
import sys

REL_FILE = "networkx/algorithms/flow/shortestaugmentingpath.py"
MODULE = "networkx.algorithms.flow.shortestaugmentingpath"
TARGET = f"{MODULE}.shortest_augmenting_path_impl"
TRACKED = {
    f"{TARGET}.<locals>.augment",
    f"{TARGET}.<locals>.relabel",
}
INVOCATION = 2

EVENT_RE = re.compile(r"\s(\S+\.py):(\d+) (\S+) event=(call|line|return|exception)\b")

QUESTION = f"""\
Test: `networkx_qa/shortestaugmentingpath_shortest_augmenting_path_impl_s6_calls/files/testcase.py`, \
class `TestShortestAugmentingPathBatch`, method `test_batch_of_max_flows` \
(pytest id `networkx_qa/shortestaugmentingpath_shortest_augmenting_path_impl_s6_calls/files/testcase.py::TestShortestAugmentingPathBatch::test_batch_of_max_flows`).

Target function: `{TARGET}` (file `{REL_FILE}`). The test never calls it directly; it is reached through \
`networkx.maximum_flow_value(..., flow_func=shortest_augmenting_path, ...)`.

Number the invocations of `shortest_augmenting_path_impl` 1, 2, 3, ... in chronological order of their \
Python `call` events (function entry) over the whole test run. Consider ONLY invocation number {INVOCATION}.

Tracked functions (exactly these two, both nested functions defined inside the target):
  - `{TARGET}.<locals>.augment`
  - `{TARGET}.<locals>.relabel`

Report the ordered sequence of every call (Python `call` event, i.e. each time the function is entered) to \
one of the two tracked functions that happens while invocation {INVOCATION} of the target is executing \
(between its entry and its return). Every call is listed separately, in chronological order; repeated calls \
are NOT deduplicated. Calls to any other function (e.g. `CurrentEdge.move_to_next`, `build_residual_network`, \
`edmonds_karp_core`, builtins such as `min`) are excluded, and the target function itself is not listed. \
(Both tracked functions are only ever called directly from the target's own frame and are not generators.)

Answer format: JSON object `{{"function_call_order": [{{"file": str, "func": str}}, ...]}}` where each \
element is one call, `file` is the repo-relative path `{REL_FILE}` and `func` is the dotted \
`module.qualname` of the called function, using Python's `__qualname__` including the `<locals>` \
component — e.g. a nested function `helper` inside `pkg.mod.outer` is written `pkg.mod.outer.<locals>.helper`. \
If no tracked call occurred the list would be empty."""


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
    for line in lines:
        m = EVENT_RE.search(line)
        if not m:
            continue
        path, lineno, func, ev = m.groups()
        if not path.replace("\\", "/").endswith(REL_FILE):
            continue
        events.append((func, ev, int(lineno)))

    target_events = [e for e in events if e[0] == TARGET]
    if not target_events:
        sys.exit("ERROR: zero trace events for target function")

    inv = 0
    depth = 0  # active frames of the target (non-recursive, but track anyway)
    active = False
    seq = []
    finished = False
    for func, ev, _ in events:
        if func == TARGET and ev == "call":
            inv += 1
            depth += 1
            if inv == INVOCATION and depth == 1:
                active = True
            continue
        if func == TARGET and ev == "return":
            depth -= 1
            if active and depth == 0:
                active = False
                finished = True
                break
            continue
        if active and ev == "call" and func in TRACKED:
            seq.append({"file": REL_FILE, "func": func})

    if inv < INVOCATION:
        sys.exit(f"ERROR: only {inv} invocations of target traced")
    if not finished:
        sys.exit("ERROR: invocation never returned in trace")
    if not seq:
        sys.exit("ERROR: no tracked calls in requested invocation")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    total = sum(1 for f, e, _ in events if f == TARGET and e == "call")
    print(f"invocations traced: {total}; tracked calls in invocation {INVOCATION}: {len(seq)}")
    print("".join(e["func"].rsplit(".", 1)[1][0] for e in seq))


if __name__ == "__main__":
    main()
