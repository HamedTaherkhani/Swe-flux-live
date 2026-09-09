from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/qualify_tables.py"
TARGET_FUNC = "sqlglot.optimizer.qualify_tables.qualify_tables"
INVOCATION = 2
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run exactly the pytest test
`sqlglot_qa/qualify_tables_qualify_tables_s1_cfg/files/testcase.py::TestQualifyTablesControlFlow::test_generated_scope_forest`.
For the second invocation of
`sqlglot.optimizer.qualify_tables.qualify_tables` in
`sqlglot/optimizer/qualify_tables.py`, report its exact executed path.

An invocation is one Python `call` event for exactly that function and
invocations are numbered starting at 1 in chronological call-event order over
the stated test run. Select invocation 2. Count only Python `line` events from
that invocation's own frame, from its `call` through its matching `return`.
Do not include the `call`, `return`, or `exception` events themselves. Events
from callers, callees, the nested local functions, comprehensions, and any
other frame do not count.

Report each retained event in chronological execution order. Do not sort or
deduplicate: if one source statement executes repeatedly, repeat its object
once per retained event, preserving the event order; consequently no
tie-breaker is needed. Line numbers are 1-based physical source lines in the
named repository file as it exists for this test. The `def` line, decorators,
and the function docstring do not appear because they are not retained
function-body `line` events.

This function contains multi-line calls and conditions. Normalize every
retained event to the line where its enclosing Python statement begins. More
precisely, among AST statement nodes whose source span contains the physical
event line, use the innermost node: the one with the greatest starting line,
then the smallest ending line. Thus, for example, an event on a continuation
line of a call whose statement opens on line 7 is reported as line 7. This
normalization is applied independently to every event, so multiple physical
events can produce repeated normalized line numbers.

Return exactly one JSON object with key `executed_path`. Its value is a JSON
list of objects, each having exactly `file`, `func`, and `line`. In every
element, `file` is the JSON string
`sqlglot/optimizer/qualify_tables.py`, `func` is the fully dotted
module-and-qualname JSON string
`sqlglot.optimizer.qualify_tables.qualify_tables` (the naming format is
`package.module.Class.method` when a class is present), and `line` is a JSON
integer. No value uses `repr`, and there is no null or missing-value
convention because all three fields are always present."""


def statement_line_map(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "qualify_tables"
    )
    if target.end_lineno is None:
        raise RuntimeError(f"cannot determine source span for {TARGET_FUNC}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node.end_lineno is not None
        and target.lineno < node.lineno <= target.end_lineno
    ]
    line_map = {}
    for line in range(target.lineno + 1, target.end_lineno + 1):
        candidates = [node for node in statements if node.lineno <= line <= node.end_lineno]
        if candidates:
            innermost = max(
                candidates,
                key=lambda node: (node.lineno, -(node.end_lineno - node.lineno)),
            )
            line_map[line] = innermost.lineno
    return line_map


def executed_path(trace_path: Path, line_map: dict[int, int]) -> list[dict[str, object]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    invocations: list[list[int]] = []
    active: list[int] | None = None
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if active is not None:
                raise RuntimeError(f"overlapping invocations for non-recursive {TARGET_FUNC}")
            active = []
            invocations.append(active)
        elif event == "line":
            if active is None:
                raise RuntimeError(f"line event outside an invocation for {TARGET_FUNC}")
            physical_line = int(match.group("line"))
            if physical_line not in line_map:
                raise RuntimeError(f"cannot map target line event at line {physical_line}")
            active.append(line_map[physical_line])
        elif event == "return":
            if active is None:
                raise RuntimeError(f"return event outside an invocation for {TARGET_FUNC}")
            active = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active is not None:
        raise RuntimeError(f"trace ended during an invocation of {TARGET_FUNC}")
    if len(invocations) < INVOCATION:
        raise RuntimeError(
            f"trace contains {len(invocations)} invocation(s), cannot select {INVOCATION}"
        )
    selected = invocations[INVOCATION - 1]
    if not selected:
        raise RuntimeError(f"invocation {INVOCATION} contains no line events")

    return [
        {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
        for line in selected
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    answer = {
        "executed_path": executed_path(
            args.trace_log,
            statement_line_map(root / TARGET_FILE),
        )
    }
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
