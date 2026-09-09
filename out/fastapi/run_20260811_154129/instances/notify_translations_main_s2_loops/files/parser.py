#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "scripts.notify_translations.main"
LOOP_HEADER_LINE = 354
LOOP_BODY_FIRST_LINE = 355

QUESTION = """Run only the pytest test `fastapi_qa/notify_translations_main_s2_loops/files/testcase.py::TestGeneratedTranslationNotifications::test_generated_discussion_matrix`. During that test run, consider the first invocation of the exact function `scripts.notify_translations.main` in `scripts/notify_translations.py`.

How many iterations does the `for` loop whose header is on line 354 execute during that invocation? An invocation is one Python call of this exact function, counted 1-based in chronological order; only the first invocation is requested. For this question, one iteration is one execution of the loop body's first line, line 355 (`label = edge.node.name`), in that exact `scripts.notify_translations.main` frame. Count every such execution across all entries into the line-354 loop caused by its enclosing loop during the first invocation, in chronological order. Do not count events in callees, nested function or comprehension frames, or any other invocation. Do not remove duplicates or sort events before counting.

Line numbers are absolute, 1-based line numbers in the named repository file as it exists for the test. The loop header and first body statement are each single-line statements; decorator, `def`, docstring, and multi-line-statement conventions therefore do not affect the count.

Return `oracle_answer` with exactly the shape `{"loop_iteration_count": <integer>}`. The value is a JSON integer number, not a string and not a Python `repr()` string. This answer has one fixed key and no list elements, so no output sorting, tie-breaking, missing-value, empty-value, or JSON-null convention applies."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*scripts/notify_translations\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def harvest(trace_path: Path) -> dict[str, int]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    first_invocation_active = False
    first_invocation_finished = False
    iteration_count = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            target_calls += 1
            if target_calls == 1:
                if first_invocation_active or first_invocation_finished:
                    fail("invalid first-invocation state at target call event")
                first_invocation_active = True

        if (
            first_invocation_active
            and event == "line"
            and line_number == LOOP_BODY_FIRST_LINE
        ):
            iteration_count += 1

        if first_invocation_active and event == "return":
            first_invocation_active = False
            first_invocation_finished = True

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    if not first_invocation_finished:
        fail("the first target invocation did not produce a return event")
    if iteration_count < 15:
        fail(
            f"line-{LOOP_HEADER_LINE} loop produced only {iteration_count} iterations; "
            "expected at least 15"
        )

    return {"loop_iteration_count": iteration_count}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": harvest(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    arguments.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
