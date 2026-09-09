#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FUNC = "data.hh_rlhf_en.hh_rlhf_en._generate_examples"
LOOP_HEADER_LINE = 86
LOOP_BODY_FIRST_LINE = 87

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/hh_rlhf_en_generate_examples_s2_loops/files/testcase.py::"
    "TestHhRlhfDatasetGeneration::test_seeded_dialogues_through_builder_entrypoint`. During the "
    "first invocation of the exact function "
    "`data.hh_rlhf_en.hh_rlhf_en.HhRlhfEn._generate_examples` in "
    "`data/hh_rlhf_en/hh_rlhf_en.py`, how many iterations does the `while` loop whose header is "
    "at line 86 perform? Because the target is a generator, an invocation means one runtime entry "
    "into its generator frame, including an initial entry or a later resumption; invocations are "
    "numbered 1-based in chronological entry order across the complete test run. Only the first "
    "such invocation is considered, ending when that frame first yields, returns, or raises. An "
    "iteration means one execution in that same target frame of the loop body's first statement, "
    "the assignment beginning at line 87, after the line-86 condition has evaluated true. Count "
    "all such executions in chronological order without deduplication; executions of the loop "
    "header itself, the target's `def` line, any decorator, and lines in called functions or other "
    "frames do not count. Line numbers are absolute, 1-based source line numbers in the named "
    "repository file as checked out for the test. For a multi-line statement or expression, "
    "execution is attributed to the line on which that statement or expression begins. Return "
    "exactly one JSON object with the sole key `loop_iteration_count`; its value is the raw "
    "base-10 JSON integer count, not a string and not formatted with `str()` or `repr()`. For "
    "example, a different run with three body entries would be encoded as "
    "`{\"loop_iteration_count\": 3}`. No sorting or tie-breaking applies to this single scalar, "
    "and no duplicate iteration is removed."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*data/hh_rlhf_en/hh_rlhf_en\.py):(?P<line>\d+) "
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

    first_call_index = next(
        (index for index, (event, _line) in enumerate(events) if event == "call"),
        None,
    )
    if first_call_index is None:
        fail(f"trace contains no invocation of {TARGET_FUNC}")

    first_end_index = next(
        (
            index
            for index in range(first_call_index + 1, len(events))
            if events[index][0] == "return"
        ),
        None,
    )
    if first_end_index is None:
        fail(f"first invocation of {TARGET_FUNC} has no terminating return/yield event")

    iteration_count = sum(
        event == "line" and line == LOOP_BODY_FIRST_LINE
        for event, line in events[first_call_index + 1 : first_end_index]
    )
    if iteration_count < 15:
        fail(
            f"loop at header line {LOOP_HEADER_LINE} is insufficiently rich: "
            f"only {iteration_count} iterations"
        )

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
