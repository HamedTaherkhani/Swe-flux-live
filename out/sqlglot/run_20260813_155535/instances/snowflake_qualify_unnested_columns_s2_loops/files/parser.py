from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "sqlglot/generators/snowflake.py"
TARGET_FUNC = "sqlglot.generators.snowflake._qualify_unnested_columns"
INVOCATION = 1
LOOP_HEADER_LINE = 314
LOOP_BODY_FIRST_LINE = 315
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run exactly the pytest test
`sqlglot_qa/snowflake_qualify_unnested_columns_s2_loops/files/testcase.py::TestSnowflakeQualifyUnnestedColumnsLoops::test_generated_mixed_unnest_columns`.
For the first invocation of
`sqlglot.generators.snowflake._qualify_unnested_columns` in
`sqlglot/generators/snowflake.py`, report the exact number of iterations of
the `for column in scope.columns` loop whose header is on line 314.

An invocation is one Python `call` of exactly the named function during the
stated test run; invocations are numbered starting at 1 in chronological
call order. Select invocation 1, from that call through its matching return.
Count only execution in that invocation's own frame. Calls and execution in
callers, callees, comprehensions, or any other frame do not count.

Iteration counting is 1-based: iteration N is the Nth time the loop body's
first executable source line, line 315 (`if column.table:`), executes in the
selected invocation. The iteration count is therefore the number of Python
line-execution events at physical line 315 in that frame. Do not count
execution of the loop header itself, and do not sort or deduplicate repeated
events; each execution of line 315 contributes one. No tie-breaker is needed
because the result is a single scalar count.

Line numbers are absolute, 1-based physical source lines in the named file as
it exists for this test. No AST statement-line normalization is applied.
Continuation lines of multi-line statements retain their own physical line
numbers. The function's `def` line, decorators, and docstrings cannot
contribute because only physical line 315 is counted.

Return exactly one JSON object with the sole key `loop_iteration_count`.
Its value is the count as a JSON integer. It is a numeric value, not a
`str()` or `repr()` string; there is no null, empty, ordering, or
missing-value convention."""


def loop_iteration_count(trace_path: Path) -> int:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_count = 0
    active_invocation: int | None = None
    count = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if active_invocation is not None:
                raise RuntimeError(f"overlapping invocations for non-recursive {TARGET_FUNC}")
            invocation_count += 1
            active_invocation = invocation_count
        elif event == "line":
            if active_invocation is None:
                raise RuntimeError(f"line event outside an invocation for {TARGET_FUNC}")
            if (
                active_invocation == INVOCATION
                and int(match.group("line")) == LOOP_BODY_FIRST_LINE
            ):
                count += 1
        elif event == "return":
            if active_invocation is None:
                raise RuntimeError(f"return event outside an invocation for {TARGET_FUNC}")
            active_invocation = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_invocation is not None:
        raise RuntimeError(f"trace ended during an invocation of {TARGET_FUNC}")
    if invocation_count < INVOCATION:
        raise RuntimeError(
            f"trace contains {invocation_count} invocation(s), cannot select {INVOCATION}"
        )
    if count == 0:
        raise RuntimeError(
            f"loop at line {LOOP_HEADER_LINE} executed zero iterations in invocation {INVOCATION}"
        )

    return count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    answer = {"loop_iteration_count": loop_iteration_count(args.trace_log)}
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
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
