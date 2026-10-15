#!/usr/bin/env python
"""Derive the S3_ProgramState oracle for MultipartDecoder.next_event."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_SUFFIX = "werkzeug.sansio.multipart.MultipartDecoder.next_event"
TARGET_FILE = "src/werkzeug/sansio/multipart.py"
TEST_ID = (
    "werkzeug_qa/multipart_next_event_s3_state/files/testcase.py"
    "::TestMultipartNextEventState::test_chunked_decode"
)
OBS_LINE = 190
OBS_K = 7
VARIABLES = ["disposition", "extra", "filename", "headers", "headers_end", "match", "name"]
TRACE_LIMIT = 500

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?| exc=.*?)? locals=(?P<locals>\{.*\})$"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_source():
    src = Path(TARGET_FILE)
    if not src.exists():
        fail(f"target source missing: {TARGET_FILE}")
    lines = src.read_text().splitlines()
    if lines[OBS_LINE - 1].strip() != "self.state = State.DATA_START":
        fail(f"line {OBS_LINE} is not the expected statement: {lines[OBS_LINE - 1]!r}")
    tree = ast.parse(src.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "next_event":
            if not (node.lineno <= OBS_LINE <= node.end_lineno):
                fail("observation line outside next_event")
            return
    fail("next_event not found in source")


def parse_events(path):
    p = Path(path)
    if not p.exists():
        fail(f"trace log missing: {path}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log empty: {path}")
    events = []
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        if not m.group("func").endswith(TARGET_SUFFIX):
            continue
        events.append(
            (int(m.group("line")), m.group("event"), ast.literal_eval(m.group("locals")))
        )
    if not events:
        fail("zero events for target function in trace")
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    check_source()
    events = parse_events(args.trace_log)

    # Rebuild cumulative locals per invocation (call resets; the tracer
    # logs only changed locals on line events, and each line event shows
    # the state *before* that line runs).
    state = {}
    hits = 0
    pending = False
    snapshot = None
    for line, ev, loc in events:
        if ev == "call":
            state = {}
            pending = False
        state.update(loc)
        if pending:
            snapshot = dict(state)
            break
        if ev == "line" and line == OBS_LINE:
            hits += 1
            if hits == OBS_K:
                pending = True
    if snapshot is None:
        fail(f"line {OBS_LINE} executed only {hits} times (< {OBS_K})")

    observed = []
    for var in sorted(VARIABLES):
        if var not in snapshot:
            fail(f"variable {var} not bound at observation point")
        val = snapshot[var]
        if len(val) > TRACE_LIMIT:
            fail(f"repr of {var} truncated by tracer")
        if " at 0x" in val:
            fail(f"unstable repr for {var}: {val}")
        observed.append({"value": val, "variable": var})

    question = (
        f"While running the pytest test `{TEST_ID}` (test file "
        "`werkzeug_qa/multipart_next_event_s3_state/files/testcase.py`, class "
        "`TestMultipartNextEventState`, method `test_chunked_decode`), the method "
        "`werkzeug.sansio.multipart.MultipartDecoder.next_event` defined in "
        f"`{TARGET_FILE}` is called many times. Consider line {OBS_LINE} of that file "
        "(absolute, 1-based line number in the repository file as checked in), the "
        "statement `self.state = State.DATA_START` inside the `State.PART` branch. "
        f"Counting across the whole test run (all invocations of `next_event` together, "
        f"in chronological order), take the moment immediately after line {OBS_LINE} has "
        f"finished executing for the {OBS_K}th time (1-based count of executions of that "
        "line). At that moment, in the frame of that `next_event` invocation, report the "
        "values of the local variables `disposition`, `extra`, `filename`, `headers`, "
        "`headers_end`, `match` and `name`. Each value must be given as the Python "
        "`repr()` string of the object bound to that local name (for containers and "
        "objects, the `repr` of the whole object exactly as Python prints it: strings "
        "keep their quotes, `None` is spelled `None`, bytes appear as `b'...'` with "
        "escapes such as `\\r`/`\\n` exactly as Python's repr writes them, a "
        "`werkzeug` `Headers` object is the repr produced by its own `__repr__`, and an "
        "`re.Match` is the standard `<re.Match object; span=(...), match=...>` form; "
        "e.g. the repr of the string a'b is `\"a'b\"` and of the dict {1: 'x'} is "
        "`\"{1: 'x'}\"`). Any newline characters inside a repr string appear as real "
        "characters in the JSON string. Answer as JSON of the form "
        "{\"observed_state\": [{\"value\": <repr string>, \"variable\": <local name>}, ...]} "
        "with exactly one entry per listed variable, sorted by `variable` in ascending "
        "lexicographic order."
    )

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": observed},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
