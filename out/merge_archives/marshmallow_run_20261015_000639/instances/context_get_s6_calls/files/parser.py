#!/usr/bin/env python
"""Build the oracle for context_get_s6_calls from the line-level trace."""

import argparse
import json
import re
import sys

REL_FILE = "src/marshmallow/experimental/context.py"
MODULE = "marshmallow.experimental.context"
TRACKED = {
    f"{MODULE}.Context.__init__",
    f"{MODULE}.Context.__enter__",
    f"{MODULE}.Context.__exit__",
    f"{MODULE}.Context.get",
}
TARGET = f"{MODULE}.Context.get"
TEST_ID = (
    "marshmallow_qa/context_get_s6_calls/files/testcase.py"
    "::TestContextGetCalls::test_nested_context_lookups"
)

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = f"""Consider the pytest test `{TEST_ID}` (test file `marshmallow_qa/context_get_s6_calls/files/testcase.py`, class `TestContextGetCalls`, its single test method `test_nested_context_lookups`). The test exercises the classmethod `marshmallow.experimental.context.Context.get` (defined in `src/marshmallow/experimental/context.py`), both directly and through a `RowSchema` dump whose `fields.Function` callback calls it, while nesting `Context` scopes.

Report the cross-function executed line path through the `Context` class during the whole test method: the chronological sequence of every Python `line` event (as reported by `sys.settrace`) that executes inside the body of one of exactly these four methods of `src/marshmallow/experimental/context.py`: `Context.__init__`, `Context.__enter__`, `Context.__exit__`, and `Context.get`. Lines are recorded whenever these methods run, regardless of who called them (directly from the test, from nested helper functions, from `with` statements, or from inside marshmallow's serialization machinery). Nothing else is included: no lines from other functions or files, no `call`/`return`/`exception` events (so the `def` line and the `@classmethod` decorator line never appear, and docstring lines never appear because they produce no line events). A line that raises (e.g. a `ContextVar.get` that raises `LookupError`) still appears once, because its line event fires before the exception. Every executed line event is its own entry: no deduplication, repeated executions are listed every time, in the exact chronological order they occur during the test method (setup/teardown and module import are not part of the test method and contribute nothing).

Each entry is an object `{{"file": str, "func": str, "line": int}}` where `file` is the repo-relative path `src/marshmallow/experimental/context.py`, `func` is the dotted `<module>.<qualname>` of the method whose body the line belongs to, with module `marshmallow.experimental.context` (e.g. `marshmallow.experimental.context.Context.__enter__`), and `line` is the absolute 1-based line number in `src/marshmallow/experimental/context.py` as it exists in the repository. Answer as JSON: `{{"executed_path": [{{"file": ..., "func": ..., "line": ...}}, ...]}}`."""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except OSError as exc:
        fail(f"cannot read trace log {args.trace_log}: {exc}")
    if not raw:
        fail("trace log is empty")

    path = []
    target_calls = 0
    for text in raw:
        m = LINE_RE.match(text)
        if not m:
            continue
        file = m.group("file").replace("\\", "/")
        func = m.group("func")
        if not file.endswith(REL_FILE) or func not in TRACKED:
            continue
        event = m.group("event")
        if func == TARGET and event == "call":
            target_calls += 1
        if event == "line":
            path.append({"file": REL_FILE, "func": func, "line": int(m.group("line"))})

    if target_calls == 0:
        fail("no call events for Context.get in trace")
    if not path:
        fail("no line events for tracked Context methods in trace")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": {"executed_path": path},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"Context.get calls: {target_calls}; path length: {len(path)}")


if __name__ == "__main__":
    main()
