from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/io/core.py"
TARGET_FUNC = "kedro.io.core.parse_dataset_definition"
INVOCATION = 10
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/core_parse_dataset_definition_s1_cfg/files/testcase.py::TestDatasetDefinitionControlFlow::test_generated_configurations`
against this repository. What is the exact ordered sequence of executed source-line
events in the 10th invocation of
`kedro.io.core.parse_dataset_definition` from `kedro/io/core.py`?

Count invocations 1-based, in chronological order: an invocation is one Python
`call` event whose frame is exactly `kedro.io.core.parse_dataset_definition`.
For the requested invocation, include only Python `line` events from that exact
function frame. Exclude `call`, `return`, and `exception` events, and exclude
events from callees, generator/comprehension frames, and any other nested frame.
Keep events in chronological execution order, retain every duplicate, and do
not sort or deduplicate the sequence.

Report each event as an object with exactly the keys `file`, `func`, and `line`.
For every object, `file` is the repo-relative POSIX path
`kedro/io/core.py`, `func` is the fully qualified dotted name
`kedro.io.core.parse_dataset_definition`, and `line` is a JSON integer.
The complete answer must have exactly this JSON shape:
`{"executed_path": [{"file": "str", "func": "str", "line": "int"}]}`,
with the shown strings in that snippet serving as type placeholders rather
than answer values.

Line numbers are absolute 1-based source line numbers in the named file as it
exists in this repository. Normalize each line event to the `lineno` of its
smallest enclosing executable Python `ast.stmt` node. Thus, for a multi-line
call, assignment, warning, or condition, report the line where that enclosing
statement begins; for example, a continuation event on line 9 for a statement
beginning on line 8 is reported as 8. Apply this normalization independently
to every event, so multiple runtime events that normalize to the same line
remain multiple elements. The function's `def` line, decorator lines, and
docstring lines do not appear because they are not `line` events in the
executing function body under these rules."""


def _statement_line_map(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "parse_dataset_definition"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and hasattr(node, "end_lineno")
    ]
    result: dict[int, int] = {}
    for line in range(target.lineno, target.end_lineno + 1):
        enclosing = [
            node
            for node in statements
            if node.lineno <= line <= (node.end_lineno or node.lineno)
        ]
        if enclosing:
            smallest = min(
                enclosing,
                key=lambda node: (
                    (node.end_lineno or node.lineno) - node.lineno,
                    -node.lineno,
                ),
            )
            result[line] = smallest.lineno
    return result


def _read_invocations(trace_path: Path) -> list[list[int]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    invocations: list[list[int]] = []
    current: list[int] | None = None
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file").replace("\\", "/").endswith(f"/{TARGET_FILE}")
        ):
            continue
        target_events += 1
        event = match.group("event")
        if event == "call":
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                raise RuntimeError("target line event appeared outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            current = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if len(invocations) < INVOCATION:
        raise RuntimeError(
            f"trace contains only {len(invocations)} target invocations; "
            f"need invocation {INVOCATION}"
        )
    if not invocations[INVOCATION - 1]:
        raise RuntimeError(f"invocation {INVOCATION} contains zero line events")
    return invocations


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    line_map = _statement_line_map(source_path)
    invocations = _read_invocations(args.trace_log)
    normalized_lines = [
        line_map.get(line, line) for line in invocations[INVOCATION - 1]
    ]

    executed_path = [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
        for line in normalized_lines
    ]
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
