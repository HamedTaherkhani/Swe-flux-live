#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/dependencies/models.py"
TARGET_FUNC = "fastapi.dependencies.models._is_coroutine_callable_cached"
INVOCATION = 21

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`fastapi_qa/models_is_coroutine_callable_cached_s1_cfg/files/testcase.py::TestCoroutineCallableClassification::test_programmatic_callable_matrix`
against this repository. During that test, consider invocations of
`fastapi.dependencies.models._is_coroutine_callable_cached` whose code is in
`fastapi/dependencies/models.py`. An invocation is one `call` event for exactly
that function's frame, counted 1-based in chronological order during the test;
calls of helpers, wrappers, comprehensions, or other frames do not increment
this count.

What is the exact ordered sequence of executed source-line events in the 21st
invocation? Return exactly
`{"executed_path": [{"file": "str", "func": "str", "line": "int"}]}`, where
`executed_path` is a JSON list and each element has exactly the string keys
`file`, `func`, and `line` with value types string, string, and integer,
respectively. Include one object per retained line event in chronological
execution order. Preserve all repeated line events; do not sort or deduplicate
them. In every object, `file` is the repo-relative string
`fastapi/dependencies/models.py`, and `func` is the fully qualified dotted
module-and-function string
`fastapi.dependencies.models._is_coroutine_callable_cached`.

Count only Python `line` events emitted by the 21st target frame itself.
Exclude its `call`, `return`, and `exception` events and every event from
callees or other frames. The `line` integer is an absolute 1-based source line
number in the named file as it exists in this checkout. The function has
multi-line conditions and calls: normalize an event on any continuation line
to the line where its innermost enclosing Python statement begins.
"Innermost" means the enclosing `ast.stmt` node having the smallest inclusive
`lineno` through `end_lineno` span; ties choose the node with the later starting
line, then the smaller column offset. Each event remains a separate list item
after normalization, including when several events normalize to the same
statement-start line. The decorator and `def` lines do not appear because they
do not produce retained line events; a docstring line would appear only if a
line event for it occurred in the selected frame."""


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
            and node.name == "_is_coroutine_callable_cached"
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
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

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
    selected_file = None
    completed = False
    for event, line, traced_file in target_events:
        if event == "call":
            invocation_number += 1
            collecting = invocation_number == INVOCATION
            if collecting:
                selected_file = traced_file
        elif collecting and event == "line":
            if not traced_file.replace("\\", "/").endswith(TARGET_FILE):
                fail(f"target event came from unexpected file: {traced_file}")
            selected_lines.append(line)
        elif collecting and event == "return":
            collecting = False
            completed = True
            break

    if invocation_number < INVOCATION:
        fail(
            f"trace has only {invocation_number} target invocations; "
            f"expected at least {INVOCATION}"
        )
    if not completed:
        fail(f"selected invocation {INVOCATION} has no return event")
    if not selected_lines:
        fail(f"selected invocation {INVOCATION} has zero line events")
    if selected_file is None:
        fail("could not determine target source path from selected invocation")

    source_path = Path(selected_file)
    line_map = statement_start_map(source_path)
    normalized_lines = []
    for line in selected_lines:
        if line not in line_map:
            fail(f"line event {line} is not contained by a target statement")
        normalized_lines.append(line_map[line])

    output = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {
            "executed_path": [
                {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
                for line in normalized_lines
            ]
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote oracle with {len(normalized_lines)} executed line events to {out_path}"
    )


if __name__ == "__main__":
    main()
