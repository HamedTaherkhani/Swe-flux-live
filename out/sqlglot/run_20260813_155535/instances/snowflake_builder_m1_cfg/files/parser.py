from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/parsers/snowflake.py"
TARGET_FUNC = "sqlglot.parsers.snowflake._build_datetime.<locals>._builder"
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the unittest class selected by the pytest id
`sqlglot_qa/snowflake_builder_m1_cfg/files/testcase.py::TestSnowflakeDatetimeBuilderControlFlow`,
which runs every source-defined `test_` method in
`sqlglot_qa/snowflake_builder_m1_cfg/files/testcase.py`. The covered methods
are `test_all_path_scramble`, `test_cast_focused_rotation`,
`test_column_path_rotation`, `test_date_path_rotation`,
`test_date_timestamp_interleave`, `test_literal_path_rotation`,
`test_safe_path_rotation`, `test_time_path_rotation`,
`test_time_timestamp_interleave`, `test_timestamp_format_rotation`,
`test_timestamp_numeric_rotation`, and `test_unsafe_path_rotation`. Aggregate
the counts over all invocations made by all twelve methods in that class;
method execution order does not alter these summed counts.

For the nested target function
`sqlglot.parsers.snowflake._build_datetime.<locals>._builder` in
`sqlglot/parsers/snowflake.py`, report the total number of Python runtime
`line` events at each physical source line in its body. The body scope is
every absolute, 1-based physical line from the first body statement through
the function's final body statement, inclusive: lines 84 through 128 in this
repository. Include exactly one result object for every line in that range.
Blank lines, comment-only lines, and formatting-only continuation lines remain
in scope and receive count 0 if no runtime `line` event is reported for that
physical line. The nested function's `def` line 83 and any decorator lines are
outside the body and must not appear.

Count only `line` events from frames whose function name is exactly
`sqlglot.parsers.snowflake._build_datetime.<locals>._builder` and whose source
file is exactly `sqlglot/parsers/snowflake.py`; exclude events in the enclosing
factory, callers, callees, comprehensions, and every other frame. Each event
adds one to its line's count, including repeated events on one line and events
from repeated invocations; do not deduplicate events. One invocation means one
runtime `call` event for that exact target frame. Invocations are conceptually
numbered from 1 in chronological order across the complete class run, although
invocation numbers are not included in the answer.

For a multi-line statement or expression, attribute each event to the exact
1-based physical line supplied by Python as the event's line number, including
an executable continuation line when Python reports one; do not normalize it
to the line where the enclosing statement began. A physical line with no such
event is represented by the JSON integer `0`, never by JSON `null`, an empty
string, or an omitted object.

Return exactly one JSON object with key `line_execution_counts`. Its value is
a JSON list of objects having exactly the fields `line` and `count`, both JSON
integers. Sort the objects by `line` in strictly ascending numerical order.
Every body line appears once, so there is no tie-breaker."""


def target_body_range(source_path: Path) -> range:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    outer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_datetime"
    )
    target = next(
        node
        for node in outer.body
        if isinstance(node, ast.FunctionDef) and node.name == "_builder"
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
        if not match:
            continue

        traced_file = match.group("file").replace("\\", "/")
        if match.group("func") != TARGET_FUNC or not (
            traced_file == TARGET_FILE or traced_file.endswith(f"/{TARGET_FILE}")
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
