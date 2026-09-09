#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.sansio.blueprints.Blueprint.register"
TARGET_FILE = "src/flask/sansio/blueprints.py"
TARGET_FILE_SUFFIX = f"/{TARGET_FILE}"

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/blueprints_register_m3_state/files/testcase.py::"
    "TestBlueprintRegisterState::test_generated_nested_options`. Across every "
    "runtime invocation of `flask.sansio.blueprints.Blueprint.register` in "
    "`src/flask/sansio/blueprints.py` caused during that test, what is the "
    "sorted set of distinct states taken by the local dictionary "
    "`bp_options`? Observe the target function's own frame immediately before "
    "each source line is executed, and include an observation exactly when "
    "`bp_options` is already bound in that frame; this includes repeated loop "
    "iterations and recursively triggered invocations. Exclude call, return, "
    "and exception events, and exclude implicit comprehension or generator "
    "frames and every other callee frame. An invocation means one call of the "
    "target function during the test, numbered from 1 in chronological "
    "call-entry order; invocation numbers are not part of the answer. A line "
    "observation uses the variable values that exist immediately before the "
    "statement or expression beginning on that line executes. Source lines "
    "are absolute, 1-based lines in the named repository file; for a "
    "multi-line statement or expression, Python's line event is the line "
    "where the currently evaluated statement or expression begins. The "
    "function `def` line, decorator lines, and docstring-only lines do not "
    "produce observations for this question. For each observation, format "
    "the entire dictionary with Python `repr(bp_options)`, preserving the "
    "dictionary's runtime insertion order and using Python spellings inside "
    "the string (for example, `None` rather than JSON `null`); do not "
    "truncate, normalize, or separately sort dictionary entries. Remove "
    "duplicate repr strings across all points and invocations, then sort the "
    "remaining strings in ascending Unicode code-point lexicographic order "
    "(the same total order as Python `sorted` on strings), with no further "
    "tie-breaker because duplicates have been removed. Return a JSON object "
    "with exactly one key, `unique_values`, whose value is the resulting JSON "
    "array of JSON strings. No empty-string or JSON-null sentinel is used: "
    "every array element is exactly one Python repr string of the whole "
    "dictionary."
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_locals(raw_line: str) -> dict[str, str]:
    marker = " locals="

    if marker not in raw_line:
        fail(f"target event has no locals payload: {raw_line}")

    payload_text = raw_line.rsplit(marker, 1)[1]

    try:
        payload = ast.literal_eval(payload_text)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse target locals payload: {exc}")

    if not isinstance(payload, dict):
        fail("target locals payload is not a dictionary")

    if not all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
        fail("target locals payload does not map strings to repr strings")

    return payload


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    trace_path = Path(args.trace_log)

    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")

    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events: list[tuple[str, dict[str, str]]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)

        if match is None:
            continue

        if (
            match.group("func") == TARGET_FUNC
            and match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX)
        ):
            target_events.append((match.group("event"), parse_locals(raw_line)))

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    frame_stack: list[dict[str, str]] = []
    unique_values: set[str] = set()
    call_count = 0
    line_count = 0

    for event, changed_locals in target_events:
        if event == "call":
            call_count += 1
            frame_stack.append(dict(changed_locals))
            continue

        if not frame_stack:
            fail(f"target {event} event occurred outside an invocation")

        frame_stack[-1].update(changed_locals)

        if event == "line":
            line_count += 1

            if "bp_options" in frame_stack[-1]:
                unique_values.add(frame_stack[-1]["bp_options"])
        elif event == "return":
            frame_stack.pop()

    if call_count == 0:
        fail(f"trace has target events but no call event for {TARGET_FUNC}")

    if line_count == 0:
        fail(f"trace has no line events for {TARGET_FUNC}")

    if frame_stack:
        fail(f"{len(frame_stack)} target invocation(s) have no return event")

    if not unique_values:
        fail("no bp_options states were observed")

    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(unique_values)},
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
