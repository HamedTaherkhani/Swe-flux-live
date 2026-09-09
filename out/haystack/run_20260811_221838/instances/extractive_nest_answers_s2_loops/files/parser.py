#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "haystack.components.readers.extractive.ExtractiveReader._nest_answers"
TRACE_FRAME_FUNC = "haystack.components.readers.extractive._nest_answers"
TARGET_FILE_SUFFIX = "/haystack/components/readers/extractive.py"
LOOP_HEADER_LINE = 390
LOOP_BODY_FIRST_LINE = 391

QUESTION = (
    "Run only "
    "haystack_qa/extractive_nest_answers_s2_loops/files/testcase.py::"
    "TestExtractiveNestAnswersLoops::test_seeded_nested_answer_reconstruction. "
    "Consider invocations of "
    "haystack.components.readers.extractive.ExtractiveReader._nest_answers in "
    "haystack/components/readers/extractive.py. An invocation is one call of that exact function during the test run, "
    "numbered 1-based in chronological execution order; the test makes exactly one such invocation, so report for "
    "invocation 1. For the `while` loop whose header begins at absolute 1-based source line 390, compute the total "
    "number of iterations during that invocation. Iteration counting is 1-based in chronological order across every "
    "activation of this static loop within invocation 1: iteration N is the Nth execution in the target function's "
    "own frame of the loop body's first executable line, absolute source line 391 (`answer = "
    "answers_without_query[i]`). Count all such executions across all surrounding `for query_id` iterations. Ignore "
    "executions in nested comprehension frames, callees, and every function other than the exact target function. "
    "Line numbers are absolute, 1-based lines in the named repository file as it exists for this run. For a multi-line "
    "statement or expression, the executed line is where that statement or expression begins; decorator, `def`, and "
    "docstring lines do not count unless Python executes them in the target invocation, and in any case only an "
    "execution of line 391 counts as an iteration here. Do not deduplicate, reorder, or otherwise transform the "
    "iteration executions. Return exactly a JSON object with the sole key `loop_iteration_count`; its value must be a "
    "JSON integer. No string formatting or null representation is involved."
)

EVENT_RE = re.compile(
    r"\s(?P<file>\S+):(?P<line>\d+)\s+(?P<func>\S+)\s+"
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def count_iterations(trace_path):
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_counts = []
    active_count = None

    for raw_line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
            continue
        if match.group("func") != TRACE_FRAME_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            if active_count is not None:
                fail("encountered an overlapping target invocation")
            active_count = 0
        elif event == "line" and line == LOOP_BODY_FIRST_LINE:
            if active_count is None:
                fail("encountered a loop-body event outside a target invocation")
            active_count += 1
        elif event == "return":
            if active_count is None:
                fail("encountered a target return without a matching call")
            invocation_counts.append(active_count)
            active_count = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active_count is not None:
        fail("trace ended during a target invocation")
    if len(invocation_counts) != 1:
        fail(f"expected exactly one completed target invocation, found {len(invocation_counts)}")
    if invocation_counts[0] < 15:
        fail(f"loop scenario is too shallow: observed only {invocation_counts[0]} iterations")
    return invocation_counts[0]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    iteration_count = count_iterations(args.trace_log)
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
