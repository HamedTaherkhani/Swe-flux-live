#!/usr/bin/env python
"""Parse the trace log into the S6 function_call_order oracle for Request.get_json."""
import argparse
import json
import re
import sys

REL_FILE = "src/werkzeug/wrappers/request.py"
MOD = "werkzeug.wrappers.request"
TARGET = MOD + ".Request.get_json"
TRACKED = {
    MOD + ".Request.get_json",
    MOD + ".Request.get_data",
    MOD + ".Request.stream",
    MOD + ".Request.on_json_loading_failed",
}

LINE_RE = re.compile(r"^\S+ \S+ (\S+):(\d+) (\S+) event=(\w+)")

QUESTION = (
    "Consider the test `werkzeug_qa/request_get_json_s6_calls/files/testcase.py::"
    "TestGetJsonCallStructure::test_get_json_sequence` (test class "
    "`TestGetJsonCallStructure`, single test method `test_get_json_sequence`). "
    "During this test the method `Request.get_json` defined in "
    "`src/werkzeug/wrappers/request.py` (qualname "
    "`werkzeug.wrappers.request.Request.get_json`) is invoked many times on several "
    "`Request` objects. Track calls to exactly these four functions, all defined in "
    "`src/werkzeug/wrappers/request.py`: `werkzeug.wrappers.request.Request.get_json`, "
    "`werkzeug.wrappers.request.Request.get_data`, "
    "`werkzeug.wrappers.request.Request.stream` (the getter function of the "
    "`stream` cached_property; it counts as a call only when its function body is "
    "actually executed, not when a cached value is returned without running it), and "
    "`werkzeug.wrappers.request.Request.on_json_loading_failed`. "
    "Report the complete chronological sequence of calls (function entries) to these "
    "four functions over the whole test method, from the first to the last. Include "
    "every call, regardless of whether it is made directly by `get_json` or nested "
    "deeper (e.g. a tracked function called from another tracked function) - in this "
    "test every such call happens while some `get_json` invocation is on the stack. "
    "Each call to a tracked function produces exactly one element, including the "
    "calls to `get_json` itself; repeated calls are NOT deduplicated; calls to any "
    "other function (other werkzeug functions, properties such as `is_json`, "
    "exception constructors, json module functions, builtins) are excluded. Calls "
    "that end by raising an exception still count. Order is the order in which the "
    "calls begin. "
    "Answer format: a JSON object `{\"function_call_order\": [...]}` whose list "
    "elements are objects `{\"file\": str, \"func\": str}`, where `file` is the "
    "repo-relative path `src/werkzeug/wrappers/request.py` and `func` is the dotted "
    "`module.Class.method` qualname with module `werkzeug.wrappers.request` "
    "(e.g. `werkzeug.wrappers.request.Request.close`)."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        sys.exit(f"ERROR: cannot read trace log: {exc}")
    if not lines:
        sys.exit("ERROR: trace log is empty")

    order = []
    target_events = 0
    seen_funcs = set()
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        path, _lineno, func, event = m.groups()
        if not path.replace("\\", "/").endswith(REL_FILE):
            continue
        if func not in TRACKED:
            continue
        if func == TARGET:
            target_events += 1
        if event == "call":
            seen_funcs.add(func)
            order.append({"file": REL_FILE, "func": func})

    if target_events == 0:
        sys.exit("ERROR: no trace events for target Request.get_json")
    if not order:
        sys.exit("ERROR: no call events found")
    missing = TRACKED - seen_funcs
    if missing:
        sys.exit(f"ERROR: tracked functions never called: {sorted(missing)}")
    if order[0]["func"] != TARGET:
        sys.exit("ERROR: first tracked call is not get_json")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": order},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
