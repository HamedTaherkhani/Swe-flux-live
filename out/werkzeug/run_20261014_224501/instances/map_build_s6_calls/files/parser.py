#!/usr/bin/env python3
"""Derive the S6 call-order oracle for MapAdapter.build from a trace log."""

import argparse
import json
import os
import re
import sys

TARGET = "werkzeug.routing.map.MapAdapter.build"
INVOCATION = 15  # 1-based invocation of the target asked about

TRACKED = [
    "werkzeug.routing.map.Map.update",
    "werkzeug.routing.map.MapAdapter._partial_build",
    "werkzeug.routing.map.MapAdapter.build",
    "werkzeug.routing.map.MapAdapter.get_host",
    "werkzeug.routing.rules.Rule.build",
    "werkzeug.routing.rules.Rule.suitable_for",
]

EVENT_RE = re.compile(r"^\S+ \S+ (?P<file>/\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""\
Consider the pytest test `werkzeug_qa/map_build_s6_calls/files/testcase.py::TestAliasRedirectBuild::test_alias_redirects` \
(file `werkzeug_qa/map_build_s6_calls/files/testcase.py`, class `TestAliasRedirectBuild`, its single test method \
`test_alias_redirects`). During this test, each `adapter.match(...)` call hits an alias rule and ends up invoking \
the target function `werkzeug.routing.map.MapAdapter.build` defined in `src/werkzeug/routing/map.py`.

Invocations of the target are numbered 1, 2, 3, ... in chronological order of their Python `call` events over the \
whole test run (invocation N = the N-th time `MapAdapter.build` is entered). Focus on invocation {INVOCATION}.

Tracked function set (exactly these six functions, identified by dotted `module.qualname`):
- `werkzeug.routing.map.Map.update` (file `src/werkzeug/routing/map.py`)
- `werkzeug.routing.map.MapAdapter._partial_build` (file `src/werkzeug/routing/map.py`)
- `werkzeug.routing.map.MapAdapter.build` (file `src/werkzeug/routing/map.py`)
- `werkzeug.routing.map.MapAdapter.get_host` (file `src/werkzeug/routing/map.py`)
- `werkzeug.routing.rules.Rule.build` (file `src/werkzeug/routing/rules.py`)
- `werkzeug.routing.rules.Rule.suitable_for` (file `src/werkzeug/routing/rules.py`)

Report the ordered sequence of calls to tracked functions that start while invocation {INVOCATION} of \
`MapAdapter.build` is on the call stack, i.e. strictly after that invocation is entered and before it returns. \
Inclusion rule: count calls TRANSITIVELY (calls made directly by the target's frame AND calls made from any deeper \
frame, e.g. `Rule.suitable_for` called by `MapAdapter._partial_build`, are all included). Do NOT include the \
entry of invocation {INVOCATION} itself. Every call is listed each time it happens (no deduplication), including \
calls that return early or return `None`. Calls to any function not in the tracked set (builtins, comprehension \
frames, lambdas, methods of other classes such as converters, matcher methods, `Rule._build`/`Rule._build_unknown` \
compiled builder functions, `MapAdapter.make_redirect_url`, etc.) are ignored entirely and do not appear, but tracked \
functions they call still count. None of the tracked functions are generators. Order = chronological order in which \
each call begins.

Answer format: a JSON object `{{"function_call_order": [{{"file": ..., "func": ...}}, ...]}}` where each element \
describes one call: `file` is the repo-relative path of the file defining the called function (e.g. \
`src/werkzeug/routing/rules.py`), and `func` is its dotted `module.qualname` exactly as written in the tracked list \
above (e.g. `werkzeug.routing.rules.Rule.suitable_for`; no `src.` prefix, no bare names)."""


def rel_path(abs_file):
    norm = abs_file.replace("\\", "/")
    idx = norm.rfind("/src/werkzeug/")
    if idx < 0:
        raise SystemExit(f"ERROR: unexpected file path in trace: {abs_file}")
    return norm[idx + 1 :]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        sys.exit(f"ERROR: trace log missing or empty: {args.trace_log}")

    events = []
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = EVENT_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            ev = m.group("event")
            if ev not in ("call", "return"):
                continue
            events.append((ev, m.group("func"), rel_path(m.group("file"))))

    if not any(ev == "call" and func == TARGET for ev, func, _ in events):
        sys.exit("ERROR: no call events for target function in trace")
    seen_funcs = {func for ev, func, _ in events if ev == "call"}
    missing = sorted(set(TRACKED) - seen_funcs)
    if missing:
        sys.exit(f"ERROR: tracked functions never seen in trace: {missing}")
    unexpected = sorted(seen_funcs - set(TRACKED))
    if unexpected:
        sys.exit(f"ERROR: untracked functions appeared in trace: {unexpected}")

    # Walk call/return events with an explicit stack to delimit invocation N.
    stack = []
    target_count = 0
    capture_depth = None
    order = []
    done = False
    for ev, func, path in events:
        if ev == "call":
            if capture_depth is not None:
                order.append({"file": path, "func": func})
            stack.append(func)
            if func == TARGET and capture_depth is None and not done:
                target_count += 1
                if target_count == INVOCATION:
                    capture_depth = len(stack)
        else:
            if not stack:
                sys.exit("ERROR: unbalanced return event in trace")
            if capture_depth is not None and len(stack) == capture_depth:
                if stack[-1] != TARGET:
                    sys.exit("ERROR: stack mismatch at target return")
                capture_depth = None
                done = True
            stack.pop()

    if target_count < INVOCATION:
        sys.exit(f"ERROR: only {target_count} target invocations, need {INVOCATION}")
    if not done:
        sys.exit("ERROR: target invocation never returned")
    if not order:
        sys.exit("ERROR: empty call order")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": order},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
