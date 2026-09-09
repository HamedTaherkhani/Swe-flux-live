#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FUNC = "llamafactory.train.kto.trainer.log"
TARGET_CALL_LINE = 260
LOOP_HEADER_LINE = 291
LOOP_BODY_FIRST_LINE = 292

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/trainer_log_m2_loops/files/testcase.py::"
    "TestKTOLoggingLoopDynamics::test_seeded_periodic_logging`. Across all invocations of the exact "
    "function `llamafactory.train.kto.trainer.CustomKTOTrainer.log` in "
    "`src/llamafactory/train/kto/trainer.py` during that test, determine the maximum and minimum "
    "iteration counts of the `for key, metric in metric_dict.items()` loop whose header begins at "
    "line 291. An invocation means one runtime `call` entry into that exact function during the "
    "complete test; include every invocation and number invocations 1-based in chronological entry "
    "order. For each invocation separately, an iteration means one execution in that function's own "
    "frame of the loop body's first statement, the `if not key.startswith(\"dummy_\"):` statement "
    "beginning at line 292. Count executions chronologically and without deduplication; if the "
    "line-291 loop were entered more than once in one invocation, sum all of its iterations for that "
    "invocation. An invocation in which the body never executes has iteration count zero. Take "
    "`max_iterations` and `min_iterations` over the multiset of all per-invocation counts; retain "
    "duplicate counts when forming that multiset, although duplicates do not alter either extremum. "
    "Only executions in the exact target function frame count: exclude the `def` line, decorator "
    "lines, loop-header executions, and executions in called functions, comprehensions, or any other "
    "frame. Line numbers are absolute, 1-based source line numbers in the named repository file as "
    "checked out for the test. For a multi-line statement or expression, execution is attributed to "
    "the line where that statement or expression begins. Return exactly one JSON object with keys in "
    "this order: `max_iterations`, then `min_iterations`; each value must be a raw base-10 JSON "
    "integer, not a string. For example, the required serialization shape is "
    "`{\"max_iterations\": 8, \"min_iterations\": 2}`. Do not add keys. No sorting or tie-breaking "
    "is needed beyond taking the stated extrema, and no `repr()` or `str()` formatting applies "
    "because both leaves are JSON integers."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/train/kto/trainer\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((match.group("event"), int(match.group("line"))))

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation_counts = []
    active_count = None
    for event, line in events:
        if event == "call":
            if line != TARGET_CALL_LINE:
                fail(f"unexpected target call line {line}; expected {TARGET_CALL_LINE}")
            if active_count is not None:
                fail("overlapping target invocations are not supported")
            active_count = 0
        elif active_count is not None and event == "line" and line == LOOP_BODY_FIRST_LINE:
            active_count += 1
        elif active_count is not None and event == "return":
            invocation_counts.append(active_count)
            active_count = None

    if active_count is not None:
        fail("final target invocation has no return event")
    if not invocation_counts:
        fail(f"trace contains no complete invocations of {TARGET_FUNC}")
    if len(set(invocation_counts)) < 6:
        fail(
            "scenario is insufficiently rich: expected at least six distinct per-invocation "
            f"counts for loop at line {LOOP_HEADER_LINE}, got {sorted(set(invocation_counts))}"
        )

    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {
            "max_iterations": max(invocation_counts),
            "min_iterations": min(invocation_counts),
        },
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
