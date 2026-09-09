#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/core.py"
TARGET_FUNC = "click.core.Option.get_help_extra"
INVOCATION_NUMBER = 26
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


QUESTION = """Run the single pytest test
`click_qa/core_get_help_extra_s1_cfg/files/testcase.py::TestGeneratedOptionHelp::test_seeded_option_matrix_help`
and consider `click.core.Option.get_help_extra` in `src/click/core.py`. What is
the exact ordered control-flow path of line events within the function's 26th
invocation?

An invocation is one `call` event for exactly
`click.core.Option.get_help_extra`, counted 1-based in chronological order
during this test only. Include only `line` events from that invocation's own
frame, from its call until its matching return; do not include the `call`,
`return`, or `exception` events, events in callees (including `get_default`,
comprehensions, and builtins), or events from any other invocation.

Return exactly `{"executed_path": [{"file": str, "func": str, "line": int}]}`
as JSON-compatible data. Each element represents one retained event, in
chronological execution order. Preserve repeated events and repeated line
numbers; do not sort or deduplicate the list. In every element, `file` must be
the repo-relative string `src/click/core.py`, and `func` must be the importable
dotted module-qualified name `click.core.Option.get_help_extra` (for example,
a method `run` on class `Worker` in module `pkg.jobs` would be written
`pkg.jobs.Worker.run`).

Line numbers are 1-based source line numbers in the named file as it exists in
the repository. The function's `def` line does not appear because it is a
`call` event rather than a `line` event; decorator lines and docstring lines
would likewise not be included unless they generated a retained line event in
this invocation. For a multi-line statement, call, or condition, report the
line where that statement begins: specifically, if an event is attributed to
a continuation line in a statement's header or right-hand-side expression,
normalize it to that enclosing statement's starting line, while events in the
statement's body retain the starting line of their own statement. Preserve
multiple events even when this normalization gives them the same line number."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def target_node(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Option":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "get_help_extra":
                    return child
    fail("could not locate Option.get_help_extra in target source")


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
            values = getattr(node, field, [])
            for value in values:
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
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        event = match.group("event")
        if event == "call":
            if current is not None:
                fail("encountered nested target call before prior invocation ended")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("encountered target line event outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            if current is None:
                fail("encountered target return event outside an invocation")
            current = None

    if current is not None:
        fail("trace ended before the final target invocation returned")
    return invocations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    invocations = parse_invocations(trace_text)
    if not invocations:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if len(invocations) <= INVOCATION_NUMBER:
        fail(
            f"need a middle 26th invocation, but trace has only {len(invocations)}"
        )

    selected = invocations[INVOCATION_NUMBER - 1]
    if not selected:
        fail("selected invocation contains zero line events")

    repo_root = Path(__file__).resolve().parents[3]
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    source = source_path.read_text(encoding="utf-8")
    function = target_node(source)
    normalize = statement_start_map(function)

    if any(line < function.lineno or line > function.end_lineno for line in selected):
        fail("selected invocation contains a line outside the target function")

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
