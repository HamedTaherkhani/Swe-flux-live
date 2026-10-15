#!/usr/bin/env python
"""Trace -> oracle.json for decorators_set_hook_s1_cfg (S1_IntraProceduralCFG)."""
import argparse
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/decorators.py"
TARGET_QUAL = "marshmallow.decorators.set_hook"
TEST_ID = (
    "marshmallow_qa/decorators_set_hook_s1_cfg/files/testcase.py"
    "::HookRegistrationTest::test_generated_schema_hooks"
)
FIRST_INV = 9
LAST_INV = 20

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    f"Run the pytest test `{TEST_ID}` (test file "
    "`marshmallow_qa/decorators_set_hook_s1_cfg/files/testcase.py`, test class "
    "`HookRegistrationTest`, its single test method `test_generated_schema_hooks`). "
    f"Consider the function `{TARGET_QUAL}` (`set_hook`, defined at module level in "
    f"`{TARGET_REL}`). An invocation is one call of `set_hook` (one Python frame of it "
    "being entered) during this test, regardless of who calls it (the public decorators "
    "`pre_dump`, `post_dump`, `pre_load`, `post_load`, `validates`, `validates_schema`, or "
    "a `functools.partial` object that later calls `set_hook` itself); invocations are "
    "numbered 1-based in chronological order of entry. Only calls made while the test "
    "method runs count (nothing happens at module import time). "
    f"Give the executed path of invocations {FIRST_INV} through {LAST_INV} inclusive: "
    "for each of these invocations in order, list the source lines of `set_hook` that "
    "execute in that invocation's own frame, in execution order, then concatenate those "
    "per-invocation lists in invocation order into one list (no separators between "
    "invocations, no deduplication: a line that executes in several invocations appears "
    "once per execution). A line is listed each time Python's line tracer (a "
    "`sys.settrace` 'line' event, CPython 3.11 as installed here) reports it for that frame; "
    "the `def` line / signature lines, the docstring, comments and blank lines never "
    "appear; 'call', 'return' and 'exception' events contribute no entries; a `try:` line "
    "and an `except ...:` clause line appear whenever the tracer reports them. Every "
    "statement in `set_hook` fits on one physical line, so each entry is simply that "
    "statement's line. Lines executed inside other functions called from `set_hook` are "
    "not included. Line numbers are absolute and 1-based in "
    f"`{TARGET_REL}` as it exists in the repository. "
    "Answer as a JSON object with the single key `executed_path`, a list of objects, "
    "each with exactly the keys `file` (str, the repo-relative path, always "
    f"\"{TARGET_REL}\"), `func` (str, the dotted module.qualname, always "
    f"\"{TARGET_QUAL}\"), and `line` (int). The list order is the execution order "
    "described above."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    invocations = []
    target_events = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if m.group("func") != TARGET_QUAL:
            continue
        target_events += 1
        ev = m.group("event")
        if ev == "call":
            invocations.append([])
        elif ev == "line":
            if not invocations:
                fail("line event before any call event")
            invocations[-1].append(int(m.group("line")))

    if target_events == 0 or not invocations:
        fail(f"no events for {TARGET_QUAL} in {trace}")
    if len(invocations) < LAST_INV:
        fail(f"only {len(invocations)} invocations, need at least {LAST_INV}")

    path = []
    for lines in invocations[FIRST_INV - 1:LAST_INV]:
        for ln in lines:
            path.append({"file": TARGET_REL, "func": TARGET_QUAL, "line": ln})
    if not path:
        fail("empty executed path")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": path},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} path_len={len(path)} target_events={target_events}")


if __name__ == "__main__":
    main()
