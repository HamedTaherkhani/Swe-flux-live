#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.sansio.app.App._find_error_handler"
TARGET_FILE_SUFFIX = "/src/flask/sansio/app.py"
LOOP_BODY_FIRST_LINE = 887

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/app_find_error_handler_m2_loops/files/testcase.py::"
    "TestFindErrorHandlerNestedLoops::test_generated_handler_searches`. "
    "Across every invocation of "
    "`flask.sansio.app.App._find_error_handler` in "
    "`src/flask/sansio/app.py` during that test, determine the maximum and "
    "minimum per-invocation iteration counts of the innermost `for` loop "
    "whose header is on line 886 (`for cls in exc_class.__mro__:`). An "
    "invocation is one runtime `call` of that exact function; number "
    "invocations from 1 in chronological call-entry order. For each "
    "invocation, iteration N is the Nth execution in that function's frame "
    "of the loop body's first executable statement, `handler = "
    "handler_map.get(cls)`, on line 887. Since the loop can be entered "
    "multiple times within one invocation by the enclosing loops on lines "
    "879 and 880, first form one cumulative count for the invocation across "
    "all such entries. Count every execution of line 887, including ones "
    "whose lookup misses, without deduplication; do not count loop-header "
    "evaluations, executions of any other line, the `def` line, or docstring "
    "lines. Then take the ordinary integer maximum and minimum over all "
    "per-invocation cumulative counts; repeated equal counts remain separate "
    "observations, although repetition does not change either extremum. "
    "Source line numbers are absolute, 1-based line numbers in the named "
    "repository file. If a statement spans multiple source lines, its "
    "executed-line event belongs to the 1-based line where that statement "
    "begins; the counted statement here occupies only line 887. Return a "
    "JSON object with exactly two keys: `max_iterations` and "
    "`min_iterations`. Both values are JSON integers, not quoted strings; "
    "there are no string, null, container-repr, function-name, or exception-"
    "name values to format. Emit the two object keys in ascending "
    "lexicographic order. Do not sort or deduplicate invocation counts before "
    "computing the extrema, and there are no ordering ties to resolve."
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if (
            match.group("func") == TARGET_FUNC
            and match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX)
        ):
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation_counts: list[int] = []
    current_count: int | None = None

    for line_number, event in events:
        if event == "call":
            if current_count is not None:
                fail(f"nested or overlapping calls found for {TARGET_FUNC}")
            current_count = 0
        elif event == "line" and line_number == LOOP_BODY_FIRST_LINE:
            if current_count is None:
                fail("counted loop-body event occurred outside an invocation")
            current_count += 1
        elif event == "return":
            if current_count is None:
                fail("return event occurred without a preceding call event")
            invocation_counts.append(current_count)
            current_count = None

    if current_count is not None:
        fail(f"final invocation of {TARGET_FUNC} has no return event")
    if not invocation_counts:
        fail(f"trace has target events but no complete invocation of {TARGET_FUNC}")
    if min(invocation_counts) <= 0:
        fail("the selected loop executed zero iterations in an invocation")
    if len(set(invocation_counts)) < 6:
        fail("fewer than six distinct per-invocation iteration counts were observed")

    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": {
            "max_iterations": max(invocation_counts),
            "min_iterations": min(invocation_counts),
        },
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
