#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_TRACE_FUNC = "llamafactory.data.mm_plugin.process_messages"
TARGET_CALL_LINE = 1363
LOOP_HEADER_LINE = 1419
LOOP_BODY_FIRST_LINE = 1420

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/mm_plugin_process_messages_s2_loops/files/testcase.py::"
    "TestQwen2OmniLoopBehavior::test_seeded_image_expansion_through_dataset_processor`. "
    "During the first invocation of "
    "`src.llamafactory.data.mm_plugin.Qwen2OmniPlugin.process_messages` in "
    "`src/llamafactory/data/mm_plugin.py`, how many iterations does the `while` loop whose "
    "header is at line 1419 execute? An invocation means one runtime entry into that exact "
    "function, and invocations are numbered 1-based in chronological order across the whole "
    "test run. An iteration means one execution of the loop body's first statement, the "
    "`image_token_replace_length = ...` statement beginning at line 1420; count every such "
    "execution, without deduplication. Iterations are numbered 1-based in chronological order "
    "within that invocation. Line numbers are absolute, 1-based source line numbers in the named "
    "repository file. For a multi-line statement or expression, execution is attributed to the "
    "line on which that statement or expression begins; decorator and `def` lines do not count "
    "as loop-body executions. Return exactly one JSON object with the single key "
    "`loop_iteration_count` and a JSON integer value, for example "
    "`{\"loop_iteration_count\": 3}`. The integer is a raw base-10 number, not a string. "
    "Because the answer is a single scalar count, no sorting or tie-breaking applies."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/data/mm_plugin\.py):(?P<line>\d+) "
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
        if match and match.group("func") == TARGET_TRACE_FUNC:
            events.append((match.group("event"), int(match.group("line"))))

    if not events:
        fail(f"trace contains zero events for {TARGET_TRACE_FUNC}")

    first_call_index = next(
        (
            index
            for index, event in enumerate(events)
            if event == ("call", TARGET_CALL_LINE)
        ),
        None,
    )
    if first_call_index is None:
        fail(
            f"trace contains no target call event for {TARGET_TRACE_FUNC} "
            f"at line {TARGET_CALL_LINE}"
        )

    first_return_index = next(
        (index for index in range(first_call_index + 1, len(events)) if events[index][0] == "return"),
        None,
    )
    if first_return_index is None:
        fail(f"first target invocation of {TARGET_TRACE_FUNC} has no return event")

    invocation_events = events[first_call_index + 1 : first_return_index]
    iteration_count = sum(
        event == "line" and line == LOOP_BODY_FIRST_LINE for event, line in invocation_events
    )
    if iteration_count == 0:
        fail(
            f"loop at header line {LOOP_HEADER_LINE} had zero observed body entries "
            f"at line {LOOP_BODY_FIRST_LINE}"
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
