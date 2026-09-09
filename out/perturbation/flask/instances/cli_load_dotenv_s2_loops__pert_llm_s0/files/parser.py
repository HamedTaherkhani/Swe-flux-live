#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.cli.load_dotenv"
TARGET_FILE_SUFFIX = "/src/flask/cli.py"
LOOP_BODY_FIRST_LINE = 758

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/cli_load_dotenv_s2_loops/files/testcase.py::"
    "TestLoadDotenvLoopBehavior::test_cli_merges_generated_env_files`. "
    "During the first invocation of `flask.cli.load_dotenv` in "
    "`src/flask/cli.py`, what is the exact iteration count of the `for` loop "
    "whose header begins on line 757 (`for key, value in data.items():`)? "
    "An invocation is one runtime call into that function during this test "
    "run; invocations are numbered from 1 in chronological call-entry order. "
    "Source line numbers are absolute, 1-based line numbers in the named file "
    "as it exists in the repository. Iterations are also numbered from 1: "
    "iteration N is the Nth execution, in that invocation, of the loop body's "
    "first statement, the `if` statement beginning on line 758. Count every "
    "such execution, including iterations that execute `continue`; do not "
    "count evaluations of the loop header or executions of later body lines, "
    "and do not deduplicate executions. Return a JSON object containing "
    "exactly the key `loop_iteration_count`; its value must be the count as a "
    "JSON integer (not a quoted string). Object keys are emitted in ascending "
    "lexicographic order; there is only one key, so there are no ordering "
    "ties and no duplicate values to resolve."
)


def fail(message: str) -> None:
    raise RuntimeError(message)


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

    in_first_invocation = False
    saw_first_call = False
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
