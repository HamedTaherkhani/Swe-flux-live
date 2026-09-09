import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/transforms.py"
TARGET_FUNC = "sqlglot.transforms.eliminate_join_marks"
LOOP_HEADER_LINE = 943
LOOP_BODY_FIRST_LINE = 944

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run exactly this pytest node against the repository:
`sqlglot_qa/transforms_eliminate_join_marks_s2_loops/files/testcase.py::TestEliminateJoinMarksLoops::test_seeded_parenthesized_predicates`.

During that test method, consider the first invocation of
`sqlglot.transforms.eliminate_join_marks` in `sqlglot/transforms.py` and the
`while` loop whose header is line 943
(`while isinstance(p.parent, exp.Paren):`). Across every time this loop is
reached within that one function invocation, what is its total iteration
count?

Line numbers are absolute, 1-based physical lines in the named file as it
exists in this repository. An invocation is one call entry into the exact
Python function named above; invocation counting is 1-based in chronological
call-entry order during the stated pytest node, and the first invocation
extends through its matching return.

One iteration means one execution in that invocation's own function frame of
the loop body's first line, line 944 (`p.parent.replace(p)`), after the
condition at line 943 has evaluated true. Therefore, when separate executions
of the enclosing `for p in predicates` loop reach this same `while` statement,
sum all executions of line 944; iteration N is the Nth such execution in
chronological order within the invocation. Count repeated executions without
deduplication. Exclude evaluations of the loop header, all other source lines,
and executions in callees, comprehensions, or any other frame. Python
source-line events for a multi-line statement belong to the 1-based physical
line Python reports, with no normalization to the statement's first or
enclosing line. The function's `def` line, docstring lines, and any decorator
lines do not count.

Return exactly one JSON object with the single key
`loop_iteration_count`. Its value must be the total as a JSON integer in
ordinary decimal notation, not a string. There is no sorting or deduplication
step and no representation conversion such as `str()` or `repr()`. Do not
return the invocation number, loop line, per-entry subtotals, or any other
keys."""


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main():
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
    if len(invocation_counts) != 1:
        fail(f"expected exactly one target invocation, found {len(invocation_counts)}")

    line_event_count = sum(line_frequencies.values())
    if line_event_count < 80:
        fail(f"target trace is too shallow: only {line_event_count} line events")
    if len(line_frequencies) < 8:
        fail(
            "target trace has too few distinct executed lines: "
            f"{len(line_frequencies)}"
        )
    if max(line_frequencies.values(), default=0) < 15:
        fail("no target source line executed at least 15 times")
    if invocation_counts[0] < 15:
        fail(
            f"selected loop is too shallow: only {invocation_counts[0]} iterations"
        )

    oracle = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": invocation_counts[0]},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {output_path} from {line_event_count} target line events "
        f"and {invocation_counts[0]} selected-loop iterations."
    )


if __name__ == "__main__":
    main()
