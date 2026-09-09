#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.config.Config.from_prefixed_env"
TARGET_FILE_SUFFIX = "/src/flask/config.py"
LOOP_BODY_FIRST_LINE = 178

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/config_from_prefixed_env_s2_loops/files/testcase.py::"
    "TestConfigFromPrefixedEnvLoops::test_generated_nested_environment`. "
    "During the first invocation of `flask.config.Config.from_prefixed_env` "
    "in `src/flask/config.py`, what is the exact total iteration count of the "
    "inner `for` loop whose header is on line 176 "
    "(`for part in parts:`)? An invocation is one runtime call into that "
    "function during this test run; invocations are numbered from 1 in "
    "chronological call-entry order. Source line numbers are absolute, "
    "1-based line numbers in the named file as it exists in the repository. "
    "For this loop, iteration N is the Nth execution within the selected "
    "invocation of the loop body's first executable statement, the `if` "
    "statement beginning on line 178. Because the inner loop can be entered "
    "multiple times by the surrounding loop, use one cumulative count across "
    "all of its entries during that invocation. Count every execution of line "
    "178, including executions where the condition is false; do not count "
    "evaluations of either loop header, comment-only line 177, or executions "
    "of later body lines, and do not deduplicate executions. Return a JSON "
    "object containing exactly the key `loop_iteration_count`; its value must "
    "be the cumulative count as a JSON integer, not a quoted string. Emit "
    "object keys in ascending lexicographic order; there is only one key, so "
    "there are no ordering ties or duplicate values to resolve."
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue

        if (
            match.group("func") == TARGET_FUNC
            and match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX)
        ):
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    saw_first_call = False
    in_first_invocation = False
    iteration_count = 0

    for line_number, event in events:
        if not saw_first_call:
            if event == "call":
                saw_first_call = True
                in_first_invocation = True
            continue

        if in_first_invocation and event == "line" and line_number == LOOP_BODY_FIRST_LINE:
            iteration_count += 1

        if in_first_invocation and event == "return":
            in_first_invocation = False
            break

    if not saw_first_call:
        fail(f"trace has target events but no call event for {TARGET_FUNC}")
    if in_first_invocation:
        fail(f"first invocation of {TARGET_FUNC} has no return event")
    if iteration_count == 0:
        fail("the selected loop executed zero iterations")

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
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
