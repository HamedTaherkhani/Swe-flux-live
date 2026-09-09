#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_TRACE_FUNC = "llamafactory.train.trainer_utils._create_galore_optimizer"
TARGET_CALL_LINE = 194
LOOP_HEADER_LINE = 205
LOOP_BODY_FIRST_LINE = 206
SELECTED_ITERATION = 47
VARIABLE = "name"

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/trainer_utils_create_galore_optimizer_s2_loops/files/testcase.py::"
    "TestGaLoreOptimizerLoopBehavior::test_generated_module_tree_via_custom_optimizer`. "
    "During the first invocation of "
    "`llamafactory.train.trainer_utils._create_galore_optimizer` in "
    "`src/llamafactory/train/trainer_utils.py`, what is the value of the loop variable `name` "
    "on the 47th iteration of the `for name, module in model.named_modules():` loop whose header "
    "is at line 205? An invocation means one runtime entry into that exact function, and "
    "invocations are numbered 1-based in chronological order across the whole test run. An "
    "iteration means one execution of the loop body's first statement, the `if isinstance(...)` "
    "statement beginning at line 206, after the `for` statement has assigned `name` and `module`; "
    "count every such execution without deduplication. Iterations are numbered 1-based in "
    "chronological order within that invocation, so the requested value is the value assigned to "
    "`name` for that 47th body entry. Line numbers are absolute, 1-based source line numbers in "
    "the named repository file. For a multi-line statement or expression, execution is attributed "
    "to the line on which that statement or expression begins; decorator and `def` lines do not "
    "count as loop-body executions. Return exactly one JSON object with keys `nth_iteration`, "
    "`value`, and `variable`. `nth_iteration` is the raw JSON integer 47, `variable` is the raw "
    "JSON string `name`, and `value` is the raw Python `str` held by `name`, encoded as a JSON "
    "string; do not return Python `repr()` quoting around that value. For example, a different "
    "selection could be encoded as "
    "`{\"nth_iteration\": 2, \"value\": \"demo\", \"variable\": \"item\"}`. Empty values, if "
    "encountered, are represented by the JSON string `\"\"`, never JSON null or an omitted key. "
    "The output contains one selected iteration only, so no sorting or tie-breaking applies, and "
    "no duplicates are removed."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/train/trainer_utils\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
LOCALS_RE = re.compile(r"\blocals=(?P<locals>\{.*\})$")


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
        event_match = EVENT_RE.search(raw_line)
        if event_match and event_match.group("func") == TARGET_TRACE_FUNC:
            events.append(
                {
                    "event": event_match.group("event"),
                    "line": int(event_match.group("line")),
                    "raw": raw_line,
                }
            )

    if not events:
        fail(f"trace contains zero events for {TARGET_TRACE_FUNC}")

    first_call_index = next(
        (
            index
            for index, event in enumerate(events)
            if event["event"] == "call" and event["line"] == TARGET_CALL_LINE
        ),
        None,
    )
    if first_call_index is None:
        fail(f"trace contains no call event for {TARGET_TRACE_FUNC} at line {TARGET_CALL_LINE}")

    first_return_index = next(
        (
            index
            for index in range(first_call_index + 1, len(events))
            if events[index]["event"] == "return"
        ),
        None,
    )
    if first_return_index is None:
        fail(f"first invocation of {TARGET_TRACE_FUNC} has no return event")

    body_entries = [
        event
        for event in events[first_call_index + 1 : first_return_index]
        if event["event"] == "line" and event["line"] == LOOP_BODY_FIRST_LINE
    ]
    if len(body_entries) < SELECTED_ITERATION:
        fail(
            f"loop at header line {LOOP_HEADER_LINE} produced only {len(body_entries)} "
            f"body entries; cannot select iteration {SELECTED_ITERATION}"
        )

    selected = body_entries[SELECTED_ITERATION - 1]
    locals_match = LOCALS_RE.search(selected["raw"])
    if not locals_match:
        fail(f"selected line event has no parseable locals mapping: {selected['raw']}")
    try:
        changed_locals = ast.literal_eval(locals_match.group("locals"))
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse selected locals mapping: {exc}")
    if VARIABLE not in changed_locals:
        fail(f"selected line event does not contain changed local {VARIABLE!r}")
    try:
        value = ast.literal_eval(changed_locals[VARIABLE])
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot decode repr for local {VARIABLE!r}: {exc}")
    if not isinstance(value, str):
        fail(f"decoded local {VARIABLE!r} is {type(value).__name__}, expected str")

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"nth_iteration": "int", "value": "str", "variable": "str"},
        "oracle_answer": {
            "nth_iteration": SELECTED_ITERATION,
            "value": value,
            "variable": VARIABLE,
        },
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
