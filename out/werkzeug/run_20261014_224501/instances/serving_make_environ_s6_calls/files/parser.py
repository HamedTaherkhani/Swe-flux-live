#!/usr/bin/env python
"""Trace -> oracle.json for serving_make_environ_s6_calls (S6_InterProceduralCFG)."""

import argparse
import json
import re
import sys

TARGET = "werkzeug.serving.WSGIRequestHandler.make_environ"
TARGET_INVOCATION = 9  # 1-based
EVENT_RE = re.compile(r" (?P<file>\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

TEST_ID = (
    "werkzeug_qa/serving_make_environ_s6_calls/files/testcase.py"
    "::TestServingRequestCycle::test_sequence_of_requests"
)

QUESTION = f"""Consider the pytest test `{TEST_ID}` (test file `werkzeug_qa/serving_make_environ_s6_calls/files/testcase.py`, class `TestServingRequestCycle`, single test method `test_sequence_of_requests`). The test feeds a series of HTTP requests through `werkzeug.serving.BaseWSGIServer.process_request`, which ends up invoking the method `werkzeug.serving.WSGIRequestHandler.make_environ` defined in `src/werkzeug/serving.py` once per request.

Invocations of `make_environ` are numbered 1, 2, 3, ... in chronological order of their Python-level `call` (frame entry) during this single test run. Focus on invocation number {TARGET_INVOCATION}, i.e. the {TARGET_INVOCATION}th time a `make_environ` frame is entered.

Report the exact ordered sequence of function calls that happen while that invocation's frame is on the call stack (from its entry until it returns), using these inclusion rules:
- Count every Python function frame that is entered (a `call` event, in the `sys.settrace` sense) whose code object is defined in a `.py` file under `src/werkzeug/` (any werkzeug module, not only `serving.py`), whether called directly by `make_environ` or transitively by anything it calls (any nesting depth).
- Exclude the `make_environ` frame itself.
- Exclude frames whose code name starts with `<` - i.e. list/set/dict comprehensions, generator expressions and lambdas (e.g. a qualname ending in `.<locals>.<genexpr>` is never listed); consequently generator-expression resumptions do not appear either.
- Functions defined outside `src/werkzeug/` (standard library such as `urllib.parse`, `logging`, `ssl`, `socket`; the test file's own helpers) are not listed, but werkzeug functions they call back into would be.
- Property getters, dunder methods (`__init__`, `__getattr__`, `__contains__`, ...) and classmethods count like ordinary functions when their frame is entered.
- Every call is listed separately, in chronological order of entry; repeated calls of the same function are NOT deduplicated.

Answer format: `{{"function_call_order": [{{"file": str, "func": str}}, ...]}}` where each element is one call, in order. `file` is the repo-relative path of the file defining the function (e.g. `src/werkzeug/routing/map.py`). `func` is the dotted name `<module>.<qualname>` using the module's import name `werkzeug....` (no `src.` prefix) and the function's `__qualname__`, e.g. `werkzeug.routing.map.MapAdapter.match`; a property getter is named by the property name itself, e.g. a property `size` on class `Foo` in module `werkzeug.bar` would be `werkzeug.bar.Foo.size`."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        print(f"ERROR: cannot read trace log: {e}", file=sys.stderr)
        return 1
    if not lines:
        print("ERROR: trace log is empty", file=sys.stderr)
        return 1

    events = []
    for raw in lines:
        m = EVENT_RE.search(raw)
        if m:
            events.append(m.groupdict())

    target_events = [e for e in events if e["func"] == TARGET]
    if not target_events:
        print("ERROR: no events for target function in trace", file=sys.stderr)
        return 1

    invocation = 0
    depth = 0
    collecting = False
    seq = []
    finished = False
    for e in events:
        if e["func"] == TARGET:
            if e["event"] == "call":
                if depth == 0:
                    invocation += 1
                    collecting = invocation == TARGET_INVOCATION
                depth += 1
            elif e["event"] == "return":
                depth -= 1
                if depth == 0 and collecting:
                    collecting = False
                    finished = True
            continue
        if not collecting or e["event"] != "call":
            continue
        name = e["func"].rpartition(".")[2]
        if name.startswith("<"):
            continue
        path = e["file"].replace("\\", "/")
        idx = path.find("src/werkzeug/")
        if idx < 0:
            continue
        seq.append({"file": path[idx:], "func": e["func"]})

    if invocation < TARGET_INVOCATION or not finished:
        print(
            f"ERROR: target invocation {TARGET_INVOCATION} not completed "
            f"(saw {invocation} invocations)",
            file=sys.stderr,
        )
        return 1
    if not seq:
        print("ERROR: empty call sequence for target invocation", file=sys.stderr)
        return 1

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
