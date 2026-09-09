from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/instructlab/model/test.py"
TARGET_FUNC = "instructlab.model.test.test"
INNER_BODY_LINE = 170

QUESTION = (
    "Run only the pytest test "
    "`instruct_lab_qa/test_test_m2_loops/files/testcase.py::"
    "TestModelCommandLoops::test_generated_answer_shapes`. During that run, "
    "consider every invocation of `instructlab.model.test.test` defined in "
    "`src/instructlab/model/test.py`. An invocation is one call of that exact "
    "function, numbered 1-based in chronological call order; only invocations "
    "that return from the function are included. In each invocation, examine "
    "the inner `for mod, answer in models.items()` loop whose header begins at "
    "line 169. Line numbers are absolute, 1-based source-file line numbers in "
    "the named repository file. An iteration is one execution of the loop "
    "body's first line, line 170 (`print()`), in that invocation's own target "
    "frame. Thus, when the outer loop at line 165 causes the inner loop to be "
    "entered multiple times, the invocation's iteration count is the sum of "
    "all line-170 executions across those inner-loop entries. Count only "
    "executions in the exact `instructlab.model.test.test` frame; exclude "
    "events in callees, comprehensions, and any other frame. For Python "
    "multi-line statements, a line execution belongs to the absolute source "
    "line where that executed statement or expression begins; decorator "
    "lines, the `def` line, and the docstring do not count as loop iterations. "
    "Across all included invocations, compute the largest and smallest such "
    "iteration counts. Return exactly one JSON object with keys "
    "`max_iterations` and `min_iterations` in that order, each serialized as "
    "a base-10 JSON integer (not a quoted string). The extrema are taken over "
    "the per-invocation counts without sorting or deduplicating them; ties do "
    "not change either scalar result. Do not include any additional keys or "
    "prose."
)

EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_counts(trace_text: str) -> list[int]:
    target_events = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        file_name = match.group("file").replace("\\", "/")
        if not file_name.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        target_events.append(
            (match.group("event"), int(match.group("line")), raw_line)
        )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    counts = []
    active_count = None
    for event, line_number, raw_line in target_events:
        if event == "call":
            if active_count is not None:
                fail(f"overlapping target invocations near trace line: {raw_line}")
            active_count = 0
        elif event == "line" and line_number == INNER_BODY_LINE:
            if active_count is None:
                fail(f"loop line appeared outside a target invocation: {raw_line}")
            active_count += 1
        elif event == "return":
            if active_count is None:
                fail(f"target return appeared without a call: {raw_line}")
            counts.append(active_count)
            active_count = None

    if active_count is not None:
        fail("trace ended before the final target invocation returned")
    if not counts:
        fail("trace contains no completed target invocations")
    if any(count == 0 for count in counts):
        fail("at least one completed target invocation executed zero loop iterations")
    return counts


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    counts = parse_counts(trace_text)
    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": {
            "max_iterations": max(counts),
            "min_iterations": min(counts),
        },
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
