#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.debughelpers._dump_loader_info"
LOOP_BODY_FIRST_LINE = 117

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/flask/debughelpers\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`flask_qa/debughelpers_dump_loader_info_m2_loops/files/testcase.py::TestLoaderInfoLoopDynamics::test_seeded_loader_metadata`
against this repository. Across the complete execution of that test, what is
the total number of iterations of the inner `for item in value` loop whose
header is at line 116 inside `flask.debughelpers._dump_loader_info` in
`src/flask/debughelpers.py`?

An invocation is one evaluation of the call to
`flask.debughelpers._dump_loader_info` that creates a generator, counted
1-based in chronological order of the generator's initial entry. Because this
function is a generator, every resume after a `yield` remains part of the same
invocation and does not start another invocation. Include every invocation
caused by the named test, in that chronological order.

One iteration of the loop at line 116 is one execution of its body's first
line, the `yield` statement at line 117. Thus iteration N within an invocation
is the Nth execution of line 117 by that invocation. Sum those executions
across all invocations. Count only line 117 executions in the target
function's own generator frames; exclude events in its caller, callees, and
comprehension frames. Repeated executions all count, with no sorting or
deduplication.

Line numbers are absolute, 1-based source line numbers in the named
repo-relative file as it exists in this checkout. The loop header and body are
single-line statements; if a statement were multi-line, its execution would
be attributed to the line where the statement or expression begins. The
function's `def` line, decorator lines, and docstring-only lines do not count
as iterations.

Return exactly one JSON object with the sole key `total_iterations`. Its value
must be a JSON integer written as a base-10 number, not a string. No function
names, exception names, Python `repr`/`str` values, containers, empty values,
or null values are serialized in the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def count_iterations(trace_path: Path) -> int:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    iteration_count = 0

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None or match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            if (
                match.group("event") == "line"
                and int(match.group("line")) == LOOP_BODY_FIRST_LINE
            ):
                iteration_count += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if iteration_count == 0:
        fail(
            f"trace contains no executions of loop body line "
            f"{LOOP_BODY_FIRST_LINE} for {TARGET_FUNC}"
        )

    return iteration_count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": {"total_iterations": count_iterations(args.trace_log)},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
