#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/flask/cli.py"
TARGET_FUNC = "flask.cli.routes_command"
LOOP_HEADER_LINE = 1106
LOOP_BODY_FIRST_LINE = 1107

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/cli_routes_command_s2_loops/files/testcase.py::"
    "RoutesCommandLoopTest::test_generated_route_table`. During the first "
    "invocation of `flask.cli.routes_command` in the repo-relative file "
    "`src/flask/cli.py`, how many iterations does the `for` loop whose header "
    "is on line 1106 perform? An invocation means one call of exactly "
    "`flask.cli.routes_command`, counted 1-based in chronological order during "
    "that test run. An iteration means one execution of the loop body's first "
    "line, line 1107, in that same function frame; iteration numbering is "
    "1-based. Line numbers are absolute 1-based source line numbers in the "
    "named file as it exists in the repository, and an executed line is "
    "attributed to the source line where its statement or expression begins. "
    "Count every qualifying execution, with no deduplication, and exclude "
    "events in nested comprehension frames, callees, and any function whose "
    "fully qualified name is not exactly `flask.cli.routes_command`. Return "
    "exactly one JSON object with the key `loop_iteration_count`; its value "
    "must be a JSON integer. Because the answer is one scalar count, no "
    "sorting or tie-breaking rule applies."
)

EVENT_RE = re.compile(
    r"(?P<file>\S*src/flask/cli\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path: Path) -> int:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")

    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)

        if match is None:
            continue

        if (
            match.group("func") == TARGET_FUNC
            and match.group("file").replace("\\", "/").endswith(TARGET_FILE)
        ):
            target_events.append(
                (int(match.group("line")), match.group("event"))
            )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    invocation = 0
    in_first_invocation = False
    iteration_count = 0

    for line_number, event in target_events:
        if event == "call":
            invocation += 1
            in_first_invocation = invocation == 1
            continue

        if in_first_invocation and event == "line":
            if line_number == LOOP_BODY_FIRST_LINE:
                iteration_count += 1

        if in_first_invocation and event == "return":
            in_first_invocation = False

    if invocation == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")

    if iteration_count == 0:
        fail(
            f"loop at line {LOOP_HEADER_LINE} had no observed iterations "
            "in the first invocation"
        )

    return iteration_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    answer = parse_trace(args.trace_log)
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": answer},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
