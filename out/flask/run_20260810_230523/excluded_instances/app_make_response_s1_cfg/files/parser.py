import argparse
import ast
import json
from pathlib import Path
import re
import sys


INSTANCE_TEST = (
    "flask_qa/app_make_response_s1_cfg/files/testcase.py::"
    "TestResponseMatrix::test_seeded_dispatch_matrix"
)
TARGET_FILE = "src/flask/app.py"
TARGET_FUNC = "flask.app.Flask.make_response"
INVOCATION = 10

QUESTION = f"""Run the pytest test `{INSTANCE_TEST}` against this repository. During that
test, what is the exact ordered sequence of executed Python line events inside
the {INVOCATION}th invocation of `{TARGET_FUNC}` in `{TARGET_FILE}`?

An invocation is one `call` event for exactly `{TARGET_FUNC}`, counted 1-based
in chronological order over the entire test run. Consider only `line` events
from that invocation's own frame. Ignore its `call`, `return`, and `exception`
events, and ignore every event in nested callees or any other frame.

Report events in chronological occurrence order (the first observed line event
first); this occurrence order is the complete ordering rule and has no
additional tie-breaker. Preserve repeated line events without sorting or
deduplication. Line numbers are 1-based physical lines in `{TARGET_FILE}` as it
exists in the repository. Normalize an event on any continuation line of a
multi-line statement to the line where the smallest enclosing AST statement
begins; for example, all event lines belonging to the arguments of a
parenthesized assignment are attributed to that assignment's first line.
Preserve each event after normalization, even when this creates adjacent
duplicates. The function's `def` line, decorator lines, and docstring lines do
not appear: execution begins at the first executable statement in its body.

Return exactly one JSON object with the shape
`{{"executed_path": [{{"file": "str", "func": "str", "line": "int"}}]}}`.
For every element, `file` must be the literal repo-relative POSIX path
`{TARGET_FILE}`, `func` must be the full runtime dotted
`module.qualname` `{TARGET_FUNC}` (the naming format is like
`package.Widget.run`), and `line` must be the normalized integer line number
defined above. Do not include any other keys."""


def statement_start_lines(source_path: Path) -> dict[int, int]:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read target source {source_path}: {exc}") from exc

    tree = ast.parse(source, filename=str(source_path))
    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Flask":
            target = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "make_response"
                ),
                None,
            )
            break
    if target is None:
        raise RuntimeError("target function Flask.make_response was not found")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and hasattr(node, "end_lineno")
        and node.end_lineno is not None
    ]
    starts = {}
    for line in range(target.lineno, target.end_lineno + 1):
        containing = [
            node for node in statements if node.lineno <= line <= node.end_lineno
        ]
        if containing:
            smallest = min(
                containing,
                key=lambda node: (node.end_lineno - node.lineno, -node.lineno),
            )
            starts[line] = smallest.lineno
    return starts


def parse_trace(trace_path: Path, source_path: Path) -> dict:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        r"(?P<file>\S*src/flask/app\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    invocations = []
    current = None
    target_events = 0

    for raw in trace_path.read_text(encoding="utf-8").splitlines():
        match = pattern.search(raw)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        if event == "call":
            if current is not None:
                raise RuntimeError("overlapping target invocations in trace")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                raise RuntimeError("target line event occurred outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            if current is None:
                raise RuntimeError("target return event occurred outside an invocation")
            current = None

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET_FUNC}"
        )
    if current is not None:
        raise RuntimeError("trace ended during a target invocation")
    if len(invocations) < INVOCATION:
        raise RuntimeError(
            f"trace has only {len(invocations)} target invocations; "
            f"need invocation {INVOCATION}"
        )

    selected = invocations[INVOCATION - 1]
    if not selected:
        raise RuntimeError(f"target invocation {INVOCATION} has no line events")

    starts = statement_start_lines(source_path)
    try:
        normalized = [starts[line] for line in selected]
    except KeyError as exc:
        raise RuntimeError(
            f"executed target line {exc.args[0]} is outside every target statement"
        ) from exc

    return {
        "executed_path": [
            {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
            for line in normalized
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    answer = parse_trace(args.trace_log, root / TARGET_FILE)
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
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote oracle to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
