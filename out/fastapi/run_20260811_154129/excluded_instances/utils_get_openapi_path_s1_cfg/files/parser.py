#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/openapi/utils.py"
TARGET_FUNC = "fastapi.openapi.utils.get_openapi_path"
INVOCATION = 2

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


QUESTION = """Run the pytest test
`fastapi_qa/utils_get_openapi_path_s1_cfg/files/testcase.py::TestGeneratedOpenAPISchema::test_schema_for_programmatic_routes`
against this repository. During that test, consider invocations of
`fastapi.openapi.utils.get_openapi_path` whose code is in
`fastapi/openapi/utils.py`. An invocation is one `call` event for exactly that
function's frame (not a nested comprehension frame), counted 1-based in
chronological order during the test.

What is the exact ordered sequence of executed source-line events in the
second invocation? Return exactly
`{"executed_path": [{"file": "str", "func": "str", "line": "int"}]}`, with
one object per line event in chronological execution order. Preserve repeated
line events; do not sort or deduplicate them. In every object, `file` is the
repo-relative string `fastapi/openapi/utils.py`, `func` is the fully qualified
dotted string `fastapi.openapi.utils.get_openapi_path`, and `line` is the
absolute 1-based source line number in that file as checked out for this test.

Count only `line` events emitted by the second target frame itself. Exclude its
`call`, `return`, and `exception` events, all events from callees, and events
from comprehension frames even when their qualified names begin with the
target name. Each retained event contributes exactly one object. The function
contains multi-line calls, conditions, comprehensions, and literals: if an
event's interpreter line is a continuation line inside a multi-line statement,
normalize `line` to the line where the innermost enclosing Python statement
begins. Here, "innermost" means the enclosing `ast.stmt` node with the smallest
inclusive `lineno` through `end_lineno` span; ties use the node with the later
starting line. Thus continuation lines are never reported as their own source
locations, but multiple events normalized to the same starting line remain as
duplicates. The `def` line and any decorator lines do not appear in the
sequence."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def statement_start_map(source_path: Path) -> dict[int, int]:
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "get_openapi_path"
        ),
        None,
    )
    if target is None or target.end_lineno is None:
        fail(f"could not locate target function in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and node.end_lineno is not None
    ]
    mapping = {}
    for line in range(target.lineno + 1, target.end_lineno + 1):
        enclosing = [
            node for node in statements if node.lineno <= line <= node.end_lineno
        ]
        if enclosing:
            chosen = min(
                enclosing,
                key=lambda node: (
                    node.end_lineno - node.lineno,
                    -node.lineno,
                    node.col_offset,
                ),
            )
            mapping[line] = chosen.lineno
    return mapping


def main() -> None:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            target_events.append(
                (match.group("event"), int(match.group("line")), match.group("file"))
            )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation_number = 0
    collecting = False
    selected_lines = []
    for event, line, traced_file in target_events:
        if event == "call":
            invocation_number += 1
            collecting = invocation_number == INVOCATION
        elif collecting and event == "line":
            if not traced_file.replace("\\", "/").endswith(TARGET_FILE):
                fail(f"target event came from unexpected file: {traced_file}")
            selected_lines.append(line)
        elif collecting and event == "return":
            collecting = False
            break

    if invocation_number < INVOCATION:
        fail(
            f"trace has only {invocation_number} target invocations; "
            f"expected at least {INVOCATION}"
        )
    if not selected_lines:
        fail(f"second invocation of {TARGET_FUNC} has zero line events")

    source_path = next(
        (
            Path(traced_file)
            for event, _line, traced_file in target_events
            if event == "call" and traced_file.replace("\\", "/").endswith(TARGET_FILE)
        ),
        None,
    )
    if source_path is None:
        fail("could not determine target source path from trace")
    line_map = statement_start_map(source_path)
    normalized_lines = []
    for line in selected_lines:
        if line not in line_map:
            fail(f"line event {line} is not contained by a target statement")
        normalized_lines.append(line_map[line])

    answer = {
        "executed_path": [
            {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
            for line in normalized_lines
        ]
    }
    output = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle with {len(normalized_lines)} executed line events to {out_path}")


if __name__ == "__main__":
    main()
