#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/_textwrap.py"
TARGET_FUNC = "click._textwrap.TextWrapper._wrap_chunks"
INVOCATION_NUMBER = 2
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`click_qa/textwrap_wrap_chunks_s1_cfg/files/testcase.py::TestSeededChunkWrapping::test_three_direct_wrapping_profiles`
and consider `click._textwrap.TextWrapper._wrap_chunks` in
`src/click/_textwrap.py`. What is the exact ordered control-flow path of line
events within the function's second invocation?

An invocation is one `call` event for exactly
`click._textwrap.TextWrapper._wrap_chunks` in the named file, counted 1-based
in chronological order during this test only. Select invocation 2. Include
only `line` events from that invocation's own frame, beginning after its
`call` event and ending before its matching `return` event. Do not include
`call`, `return`, or `exception` events; events in callees (including
`_handle_long_word`, `term_len`, comprehensions, and builtins); or events from
the first or third invocation.

Return exactly `{"executed_path": [{"file": str, "func": str, "line": int}]}`
as JSON-compatible data. Each list element represents one retained event in
chronological execution order; there is no secondary sorting or tie-breaker.
Preserve every repeated event and repeated line number, with no
deduplication. In every element, `file` is the repo-relative literal string
`src/click/_textwrap.py`, `func` is the importable dotted
module-and-qualname string `click._textwrap.TextWrapper._wrap_chunks`, and
`line` is an integer (not a string). For the name convention, a method `run`
on class `Worker` in module `pkg.jobs` would be `pkg.jobs.Worker.run`.

Line numbers are absolute 1-based source line numbers in the named repository
file. The function's `def` line does not appear because it corresponds to the
excluded `call` event. There are no decorators on this function, and its
docstring lines do not execute as retained `line` events. Multi-line
conditions occur in this function: for a multi-line statement, call, or
condition, normalize an event attributed to a continuation line in the
statement's header or right-hand-side expression to the enclosing statement's
starting line. Events in a statement's body retain the starting line of that
body statement. Keep multiple events when this normalization produces the
same line number."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_target(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TextWrapper":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "_wrap_chunks":
                    return child
    fail("could not locate TextWrapper._wrap_chunks in target source")


def statement_start_map(function: ast.FunctionDef) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.stmt) or isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue

        end_line = getattr(node, "end_lineno", node.lineno)
        body_starts: list[int] = []
        for field in ("body", "orelse", "finalbody", "handlers"):
            for value in getattr(node, field, []):
                if isinstance(value, ast.ExceptHandler):
                    body_starts.append(value.lineno)
                elif isinstance(value, ast.stmt):
                    body_starts.append(value.lineno)

        header_end = min(body_starts) - 1 if body_starts else end_line
        for line in range(node.lineno, header_end + 1):
            mapping[line] = node.lineno
    return mapping


def parse_invocations(trace_text: str) -> list[list[int]]:
    invocations: list[list[int]] = []
    current: list[int] | None = None

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        event = match.group("event")
        if event == "call":
            if current is not None:
                fail("encountered a nested target call before the prior call returned")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("encountered a target line event outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            if current is None:
                fail("encountered a target return event outside an invocation")
            current = None

    if current is not None:
        fail("trace ended before the final target invocation returned")
    return invocations


def main() -> None:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    invocations = parse_invocations(trace_text)
    if not invocations:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if len(invocations) < 3:
        fail(f"need a middle second invocation, but trace has only {len(invocations)}")

    selected = invocations[INVOCATION_NUMBER - 1]
    if not selected:
        fail("selected invocation contains zero line events")

    repo_root = Path(__file__).resolve().parents[3]
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    function = find_target(source_path.read_text(encoding="utf-8"))
    if any(line < function.lineno or line > function.end_lineno for line in selected):
        fail("selected invocation contains a line outside the target function")

    normalize = statement_start_map(function)
    executed_path = [
        {
            "file": TARGET_FILE,
            "func": TARGET_FUNC,
            "line": normalize.get(line, line),
        }
        for line in selected
    ]
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
