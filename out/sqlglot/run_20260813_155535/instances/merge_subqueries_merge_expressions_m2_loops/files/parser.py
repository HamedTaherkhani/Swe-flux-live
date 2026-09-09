import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/optimizer/merge_subqueries.py"
TARGET_FUNC = "sqlglot.optimizer.merge_subqueries._merge_expressions"
LOOP_HEADER_LINE = 444
LOOP_BODY_FIRST_LINE = 445

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest class node
`sqlglot_qa/merge_subqueries_merge_expressions_m2_loops/files/testcase.py::TestMergeExpressionsLoops`
against this repository, so that every test method whose name begins `test_`
in that class is run. Aggregate over all of those test methods in pytest's
collection order (the source-definition order used for this class).

For every invocation of
`sqlglot.optimizer.merge_subqueries._merge_expressions` in
`sqlglot/optimizer/merge_subqueries.py`, count the iterations of the `for`
loop whose header is at line 444 (`for i, column in
enumerate(columns_to_replace):`). What are the maximum and minimum iteration
counts among all invocations in the complete class run?

Line numbers are absolute, 1-based physical lines in the named file as it
exists in this repository. An invocation is one entry into the exact Python
function above, corresponding to one function call, and invocations are
numbered 1-based in chronological call-entry order across the complete pytest
run. Each invocation extends through its matching function return. Include
every invocation, including one with zero loop iterations if such an
invocation occurs.

For this loop, one iteration is one execution in that invocation's own frame
of the loop body's first line, line 445 (`parent = column.parent`), after the
loop has obtained its next element. Thus iteration N is the Nth execution of
line 445 caused by that loop in the same invocation. Count repeated
executions, but exclude the loop-header execution itself, all source-line
executions elsewhere in the function, and executions in callees,
comprehension frames, or any other frame. Python source-line events for
multi-line statements are attributed to the 1-based physical line reported
by Python; no normalization to an enclosing statement is applied. The
function's `def` line, decorator lines, and docstring lines do not count.

Return exactly one JSON object with exactly two keys:
`max_iterations` and `min_iterations`. Both values are JSON integers written
in ordinary decimal notation, not strings. `max_iterations` is the largest
per-invocation count and `min_iterations` is the smallest. Do not report
invocation identifiers, line numbers, intermediate counts, duplicates, or
any additional keys; key order is not semantically significant."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_event_count = 0
    invocation_counts = []
    active_invocations = []
    line_frequencies = Counter()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_event_count += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            invocation_counts.append(0)
            active_invocations.append(len(invocation_counts) - 1)
        elif event == "line":
            if not active_invocations:
                fail("target line event occurred outside an active invocation")
            line_frequencies[line] += 1
            if line == LOOP_BODY_FIRST_LINE:
                invocation_counts[active_invocations[-1]] += 1
        elif event == "return":
            if not active_invocations:
                fail("target return event occurred without a matching call")
            active_invocations.pop()

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not invocation_counts:
        fail(f"trace contains no invocation of {TARGET_FUNC}")
    if active_invocations:
        fail(f"trace ended with {len(active_invocations)} incomplete target invocation(s)")

    line_event_count = sum(line_frequencies.values())
    if line_event_count < 150:
        fail(f"target trace is too shallow: only {line_event_count} line events")
    if len(line_frequencies) < 8:
        fail(
            "target trace has too few distinct executed lines: "
            f"{len(line_frequencies)}"
        )
    if max(line_frequencies.values(), default=0) < 25:
        fail("no target source line executed at least 25 times")
    if len(set(invocation_counts)) < 6:
        fail(
            "loop dynamics are too uniform: only "
            f"{len(set(invocation_counts))} distinct iteration counts"
        )

    oracle = {
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
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} from {len(invocation_counts)} invocations "
        f"with {len(set(invocation_counts))} distinct loop counts."
    )


if __name__ == "__main__":
    main()
