from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/simplify.py"
TARGET_FUNC = "sqlglot.optimizer.simplify.Simplifier._simplify_binary"
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run all test methods in the unittest class
`TestSimplifyBinaryControlFlow` selected by the pytest id
`sqlglot_qa/simplify_simplify_binary_m1_cfg/files/testcase.py::TestSimplifyBinaryControlFlow`.
This means all twelve source-defined methods whose names begin with `test_`:
`test_generated_additions`, `test_generated_products`, `test_generated_subtractions`,
`test_mixed_divisions`, `test_numeric_predicates`, `test_string_predicates`,
`test_is_null_forms`, `test_null_safe_predicates`, `test_nulls_in_conditionals`,
`test_date_interval_arithmetic`, `test_interval_date_additions`, and
`test_date_and_cast_comparisons`. Aggregate counts over the entire class run,
including every invocation caused by every listed method.

For `sqlglot.optimizer.simplify.Simplifier._simplify_binary` in
`sqlglot/optimizer/simplify.py`, report the total number of Python runtime
`line` events at each physical source line in the function body. The body
scope is every absolute, 1-based line from the first body line through the
function's final body line, inclusive (lines 1230 through 1301 in this
repository). Include one result object for every physical line in that range.
Thus blank lines, comment-only lines, and formatting-only continuation lines
remain in scope and have count 0 when Python cannot execute them. The `def`
line and any decorator lines are outside the body and must not appear.

Count only `line` events emitted by frames whose function is exactly
`sqlglot.optimizer.simplify.Simplifier._simplify_binary`; events in callers,
callees, comprehensions, or other functions do not count. Each event adds one,
including repeated events at the same line and events from repeated
invocations; do not deduplicate. A function invocation is one runtime call of
that exact function, and invocations are conceptually numbered from 1 in
chronological call order, although invocation numbers are not reported.
For a multi-line statement or expression, attribute an event to the exact
1-based physical line reported by Python for that executable component:
do not normalize continuation-line events to the line where the enclosing
statement opened. A continuation line that receives no runtime `line` event
therefore has count 0.

Return exactly one JSON object with key `line_execution_counts`. Its value is
a list of objects with exactly the fields `line` and `count`; both field
values are JSON integers. Sort objects by `line` in strictly ascending order.
There is no secondary tie-breaker because every body line appears exactly
once."""


def target_body_range(source_path: Path) -> range:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    simplifier = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Simplifier"
    )
    target = next(
        node
        for node in simplifier.body
        if isinstance(node, ast.FunctionDef) and node.name == "_simplify_binary"
    )
    if not target.body or target.end_lineno is None:
        raise RuntimeError(f"cannot determine body range for {TARGET_FUNC}")
    return range(target.body[0].lineno, target.end_lineno + 1)


def line_counts(trace_path: Path, body_lines: range) -> list[dict[str, int]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    counts: Counter[int] = Counter()
    target_events = 0
    call_events = 0
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            call_events += 1
        elif event == "line":
            line = int(match.group("line"))
            if line not in body_lines:
                raise RuntimeError(f"target line event outside body range: {line}")
            counts[line] += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if call_events == 0:
        raise RuntimeError(f"trace contains no call events for {TARGET_FUNC}")
    if not counts:
        raise RuntimeError(f"trace contains no line events for {TARGET_FUNC}")

    return [{"count": counts[line], "line": line} for line in body_lines]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    body_lines = target_body_range(root / TARGET_FILE)
    answer = {"line_execution_counts": line_counts(args.trace_log, body_lines)}
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
