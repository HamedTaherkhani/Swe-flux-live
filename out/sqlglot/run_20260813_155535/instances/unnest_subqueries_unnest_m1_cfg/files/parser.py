from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/unnest_subqueries.py"
TARGET_FUNC = "sqlglot.optimizer.unnest_subqueries.unnest"
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the unittest class selected by the pytest id
`sqlglot_qa/unnest_subqueries_unnest_m1_cfg/files/testcase.py::TestUnnestControlFlow`.
Aggregate over ALL twelve source-defined test methods in that class:
`test_scalar_predicates`, `test_grouped_scalar_projections`,
`test_grouped_exists_projections`, `test_in_predicates`,
`test_grouped_in_predicates`, `test_aggregate_in_predicates`,
`test_any_predicates`, `test_limited_and_offset_predicates`,
`test_multi_projection_subqueries`, `test_not_in_predicates`,
`test_union_in_predicates`, and `test_join_clause_predicates`. Pytest identifies
each method by appending `::method_name` to the class id above. Counts are totals
over the complete class run, so test collection or execution order does not
otherwise affect the result.

For the exact function `sqlglot.optimizer.unnest_subqueries.unnest` in
`sqlglot/optimizer/unnest_subqueries.py`, report the total number of Python
runtime `line` events at every physical source line in its body. Determine the
body from the repository's Python syntax tree: it starts at the first statement
in the function body and ends at the function node's inclusive `end_lineno`.
Include every absolute, 1-based physical line in that inclusive range exactly
once. Blank lines, comment-only lines, and formatting-only continuation lines
are still in scope and receive count 0 when Python emits no event there. The
`def` line and decorator lines are outside the body and must not appear.

Count only `line` events from frames whose dotted name is exactly
`sqlglot.optimizer.unnest_subqueries.unnest` and whose source file is exactly
the repository-relative file named above. Events from its caller, its callees,
generator-expression or comprehension frames, and all other functions do not
count. Every matching event contributes one, including repeated events on one
line and events from repeated invocations; do not deduplicate. An invocation
means one runtime `call` of this exact function and is conceptually numbered
from 1 in chronological order across the class run, although invocation
numbers are not reported.

For a multi-line statement or expression, attribute each event to the exact
absolute, 1-based physical line reported by Python for that executable
component; do not move continuation-line events to the line where the enclosing
statement began. For example, if an unrelated call begins on line 20 but Python
reports an event for an argument expression on line 22, count line 22.

Return exactly one JSON object with the key `line_execution_counts`. Its value
is a list of objects, each with exactly the keys `count` and `line`, whose
values are JSON integers. Sort the objects by `line` in strictly ascending
order. There is no tie-breaker because every in-scope line occurs once."""


def target_body_range(source_path: Path) -> range:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "unnest"
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
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file").replace("\\", "/").endswith(TARGET_FILE)
        ):
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
