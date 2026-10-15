#!/usr/bin/env python
"""Parse the trace log into the S1_IntraProceduralCFG oracle for Schema._deserialize."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE_REL = "src/marshmallow/schema.py"
TARGET_FUNC = "marshmallow.schema.Schema._deserialize"
TARGET_INVOCATION = 14  # 1-based, chronological order of `call` events

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = f"""\
Test: `marshmallow_qa/schema_deserialize_s1_cfg/files/testcase.py`, test class `RecordValidateTest`, \
test method `test_validate_many_partial` (pytest id \
`marshmallow_qa/schema_deserialize_s1_cfg/files/testcase.py::RecordValidateTest::test_validate_many_partial`), \
run with pytest from the repository root under the container's CPython 3.11 interpreter.

Target function: `Schema._deserialize` defined in `{TARGET_FILE_REL}` (the method whose `def` starts at line 597; \
its module is imported as `marshmallow.schema`).

During this test the target is entered many times (the outer many=True call, one call per record, and calls made for \
nested schemas, including calls that are reached from inside other invocations). Count invocations 1-based in \
chronological order of their entry (i.e. the order in which a new frame of `Schema._deserialize` starts executing), \
across every schema class and every nesting depth. Consider invocation number {TARGET_INVOCATION}.

Question: what is the exact, ordered sequence of executed-line events of invocation {TARGET_INVOCATION}, from the \
moment its frame starts until it returns?

Counting rules:
- Report exactly the `line` events that CPython's `sys.settrace` delivers for that invocation's own frame, in order, \
with every repetition kept (no dedup). A line executed in several loop iterations appears once per execution.
- The `def` line (597) is NOT included (its entry is a `call` event, not a `line` event); docstring lines never appear.
- Lines executed in other frames are excluded: nested invocations of `Schema._deserialize` (their lines belong to \
those invocations, not to this one), the list/set comprehension frames (`<listcomp>`/`<setcomp>` under Python 3.11), \
the body of the nested `getter` function, and any callee.
- Several statements in this function span multiple physical lines (the multi-line `if partial is True or (...)` \
condition, the `sub_partial = [...]` comprehension, the nested `def getter(...)` with its default arguments, the \
`self._call_and_store(...)` call with keyword arguments on separate lines, the `fields = {{...}}` set comprehension and \
the `error_store.store_error(...)` call). Do NOT normalise these to the first line of the statement: report \
the line numbers exactly as the tracer's `frame.f_lineno` reports them for each line event, which under \
CPython 3.11 may include continuation lines of a statement and may return to the statement's first line \
again (e.g. a call spanning lines 10-12 could produce 10, 11, 12, 10).
- Line numbers are absolute, 1-based line numbers of `{TARGET_FILE_REL}` as it is on disk.

Answer format: a JSON object `{{"executed_path": [...]}}` where each element is \
`{{"file": "{TARGET_FILE_REL}", "func": "{TARGET_FUNC}", "line": <int>}}`; `file` is the repo-relative path and \
`func` is the dotted `module.qualname`, both identical in every element; elements are in execution order.
"""


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    log = Path(args.trace_log)
    if not log.is_file():
        fail(f"trace log missing: {log}")
    text = log.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log empty: {log}")

    invocations: list[list[int]] = []
    stack: list[int] = []
    n_events = 0
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith("/" + TARGET_FILE_REL):
            continue
        if m.group("func") != TARGET_FUNC:
            continue
        n_events += 1
        ev = m.group("event")
        line = int(m.group("line"))
        if ev == "call":
            invocations.append([])
            stack.append(len(invocations) - 1)
        elif ev == "line":
            if not stack:
                fail(f"line event outside any invocation: {raw}")
            invocations[stack[-1]].append(line)
        elif ev == "return":
            if not stack:
                fail(f"return event outside any invocation: {raw}")
            stack.pop()
    if n_events == 0:
        fail(f"no events for {TARGET_FUNC} in {log}")
    if stack:
        fail("unbalanced call/return events in trace")
    if len(invocations) < TARGET_INVOCATION:
        fail(f"only {len(invocations)} invocations, need {TARGET_INVOCATION}")

    for i, inv in enumerate(invocations, 1):
        print(f"invocation {i}: {len(inv)} line events, {len(set(inv))} distinct", file=sys.stderr)

    path = invocations[TARGET_INVOCATION - 1]
    if not path:
        fail("target invocation has no line events")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {
            "executed_path": [
                {"file": TARGET_FILE_REL, "func": TARGET_FUNC, "line": ln} for ln in path
            ]
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(path)} path elements)")


if __name__ == "__main__":
    main()
