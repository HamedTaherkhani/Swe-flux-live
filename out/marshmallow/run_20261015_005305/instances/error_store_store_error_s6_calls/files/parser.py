#!/usr/bin/env python
"""Parse the trace log into the S6_InterProceduralCFG oracle for ErrorStore.store_error."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_FILE_REL = "src/marshmallow/error_store.py"
MODULE = "marshmallow.error_store"
TARGET_FUNC = f"{MODULE}.ErrorStore.store_error"
TRACKED = {
    TARGET_FUNC,
    f"{MODULE}.copy_containers",
    f"{MODULE}.merge_errors",
}
TARGET_INVOCATION = 11  # 1-based, chronological order of `call` events

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+?):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = f"""\
Test: `marshmallow_qa/error_store_store_error_s6_calls/files/testcase.py`, test class `ErrorStoreMergeTest`, \
test method `test_store_many_errors` (pytest id \
`marshmallow_qa/error_store_store_error_s6_calls/files/testcase.py::ErrorStoreMergeTest::test_store_many_errors`), \
run with pytest from the repository root under the container's CPython 3.11 interpreter.

Target function: `ErrorStore.store_error` defined in `{TARGET_FILE_REL}` (module imported as `{MODULE}`; \
dotted name `{TARGET_FUNC}`).

The test calls the target 24 times. Invocations are numbered 1-based in chronological order of entry (each \
new frame of `ErrorStore.store_error` that starts executing is one invocation). Consider invocation number \
{TARGET_INVOCATION}.

Question: what is the exact cross-function executed-line path from the moment invocation {TARGET_INVOCATION} \
starts until it returns?

Inclusion rules:
- Tracked functions (all in `{TARGET_FILE_REL}`): `{MODULE}.ErrorStore.store_error`, \
`{MODULE}.copy_containers` and `{MODULE}.merge_errors`.
- Report every `line` event (as delivered by CPython 3.11's `sys.settrace`) executed in a frame of one of the \
tracked functions while invocation {TARGET_INVOCATION} is on the call stack: the target's own frame plus every \
nested/transitive (including recursive) call of `copy_containers` and `merge_errors`, at any depth. Keep every \
repetition (no dedup), in chronological order.
- Exclude `call`, `return` and `exception` events; therefore the `def` line of a function never appears merely \
because the function was entered. Comment and docstring lines never appear.
- Exclude lines executed in comprehension frames (under Python 3.11 the list/dict comprehensions inside \
`copy_containers` run in their own `<listcomp>`/`<dictcomp>` frames — those lines are NOT reported, although the \
`copy_containers` calls made from inside them ARE tracked and their lines ARE reported), and lines of any other \
function (e.g. `isinstance`, `dict.items`, test code).
- A `for` statement's header line produces a line event each time control returns to it, including the final \
check that finds the iterator exhausted (CPython 3.11 behaviour); report each one.
- Line numbers are absolute, 1-based line numbers of `{TARGET_FILE_REL}` as it is on disk.

Answer format: a JSON object `{{"executed_path": [...]}}` where each element is \
`{{"file": "{TARGET_FILE_REL}", "func": "<dotted module.qualname of the frame executing the line>", "line": <int>}}`. \
`file` is the repo-relative path; `func` is the dotted `module.qualname`, e.g. `{MODULE}.ErrorStore.__init__` for the \
constructor (so one of the three tracked names above). Elements are in execution order.
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

    target_calls = 0
    depth = 0  # depth of target frames on the stack (target is not recursive)
    active = False
    path: list[dict] = []
    seen_funcs: set[str] = set()
    for raw in text.splitlines():
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE_REL):
            continue
        func = m.group("func")
        if func not in TRACKED:
            continue
        seen_funcs.add(func)
        event = m.group("event")
        line = int(m.group("line"))
        if func == TARGET_FUNC:
            if event == "call":
                target_calls += 1
                depth += 1
                if target_calls == TARGET_INVOCATION:
                    if depth != 1:
                        fail("unexpected recursive target invocation")
                    active = True
                continue
            if event == "return":
                depth -= 1
                if active:
                    active = False
                continue
        if active and event == "line":
            path.append({"file": TARGET_FILE_REL, "func": func, "line": line})

    if target_calls == 0:
        fail("no call events for target function in trace")
    if target_calls < TARGET_INVOCATION:
        fail(f"only {target_calls} invocations of target; need {TARGET_INVOCATION}")
    if active:
        fail("target invocation never returned")
    if seen_funcs != TRACKED:
        fail(f"trace missing tracked functions: {sorted(TRACKED - seen_funcs)}")
    if not path:
        fail("empty executed path")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {"executed_path": path},
    }
    Path(args.out).write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"target invocations: {target_calls}; path length: {len(path)}")


if __name__ == "__main__":
    main()
