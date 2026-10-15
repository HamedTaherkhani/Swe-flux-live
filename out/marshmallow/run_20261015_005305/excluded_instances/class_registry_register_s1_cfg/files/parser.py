"""Parse the line trace of class_registry.register into oracle.json (S1_IntraProceduralCFG)."""

import argparse
import json
import os
import re
import sys

TARGET_FILE = "src/marshmallow/class_registry.py"
TARGET_FUNC = "marshmallow.class_registry.register"
FIRST_INV = 5
LAST_INV = 26
EXPECTED_INVOCATIONS = 26

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)

QUESTION = f"""\
Test: `marshmallow_qa/class_registry_register_s1_cfg/files/testcase.py::RegisterControlFlowTest::test_register_sequence` \
(test class `RegisterControlFlowTest`, single test method `test_register_sequence`).
Target function: `marshmallow.class_registry.register` (module-level function `register`) defined in `src/marshmallow/class_registry.py`; \
the test calls it directly.

Invocation counting: an invocation is one call of `register` during the test run; invocations are numbered 1-based in chronological order \
of their calls (the test makes {EXPECTED_INVOCATIONS} calls in total).

Question: give the exact ordered sequence of executed line events inside `register`'s own frame for invocations {FIRST_INV} through {LAST_INV} \
inclusive, concatenated in chronological order (all line events of invocation {FIRST_INV}, then all of invocation {FIRST_INV + 1}, and so on up to \
invocation {LAST_INV}; there are no separator elements between invocations).

What counts as a line event: exactly the `'line'` events that CPython's `sys.settrace` tracing delivers for the frame of `register` itself \
(run with the interpreter in this repository's environment). The `call` and `return` events are NOT included, so the `def` line (line 30) never \
appears; docstring and comment lines never appear. Events from other frames are excluded — in particular the generator expression passed to `any(...)` \
runs in its own frame and its events are NOT included, and neither are events of any function called from `register`. \
Multi-line statements: a statement spanning several lines (the `if classname in _registry and not any(...)` condition spans lines 57-59) is reported \
on the line(s) for which the interpreter actually emits line events in `register`'s frame; this can include a continuation line and a repeated \
event on the statement's first line — report every event exactly as emitted, in order. No deduplication: if the same line produces several events, \
including consecutively, each one is a separate element.

Answer format: {{"executed_path": [{{"file": <str>, "func": <str>, "line": <int>}}, ...]}}, one element per line event, in chronological order. \
In every element `file` is the repo-relative path `"{TARGET_FILE}"` and `func` is the dotted module.qualname `"{TARGET_FUNC}"` \
(identical in all elements); `line` is the absolute, 1-based line number in `{TARGET_FILE}` as it exists in the repository.\
"""


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        die(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines:
        die("trace log is empty")

    invocations = []
    depth = 0
    for raw in lines:
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        event = m.group("event")
        line = int(m.group("line"))
        if event == "call":
            if depth != 0:
                die("unexpected nested/recursive call of register")
            depth = 1
            invocations.append([])
        elif event == "return":
            if depth != 1:
                die("return without call")
            depth = 0
        elif event == "line":
            if depth != 1:
                die("line event outside an invocation")
            invocations[-1].append(line)

    if not invocations:
        die("zero events for target function in trace")
    if len(invocations) != EXPECTED_INVOCATIONS:
        die(f"expected {EXPECTED_INVOCATIONS} invocations, got {len(invocations)}")
    if depth != 0:
        die("trace ended inside an invocation")

    path = []
    for inv in invocations[FIRST_INV - 1:LAST_INV]:
        if not inv:
            die("invocation with no line events")
        for ln in inv:
            path.append({"file": TARGET_FILE, "func": TARGET_FUNC, "line": ln})

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {"executed_path": path},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"executed_path elements: {len(path)}; invocations: {len(invocations)}")


if __name__ == "__main__":
    main()
