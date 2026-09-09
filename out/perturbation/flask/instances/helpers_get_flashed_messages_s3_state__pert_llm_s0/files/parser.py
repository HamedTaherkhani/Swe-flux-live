#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/helpers.py"
TARGET_FUNC = "flask.helpers.get_flashed_messages"
OBSERVED_LINE = 396

QUESTION = """Run the pytest test `flask_qa/helpers_get_flashed_messages_s3_state/files/testcase.py::TestComputedFlashFiltering::test_tracks_seeded_filter_matrix`. During that test run, consider only invocations of `flask.helpers.get_flashed_messages` in `src/flask/helpers.py`. What is the complete chronological history of the local variable `flashes` immediately after every successful execution of line 396 in those invocations?

Line numbers are absolute, 1-based line numbers in `src/flask/helpers.py` as it exists in the repository. Line 396 means the statement whose expression begins on that line; this beginning-line rule also applies to any multi-line statement or expression. A successful execution is one that completes normally and reaches the next line event in the same invocation. The state immediately after line 396 is the state at that next line event. An invocation is one `call` of this exact function during the test run, numbered from 1 in chronological order. Include every successful execution of line 396 across all such invocations in chronological execution order. Do not include events or locals from the test setup, callers, callees, lambda or comprehension frames, or any other function. The function's `def` line, decorator lines, and docstring lines are irrelevant unless Python executes them as line events in this exact function frame.

Return exactly one JSON object with the shape `{"temporal_value_history": ["..."]}`. The `temporal_value_history` value is a JSON array with exactly one entry per included successful execution, in chronological order; preserve duplicates and do not sort or deduplicate the entries. Each entry is the full Python `repr()` string of the concrete value of `flashes` at that observation point, not `str()` and not a JSON rendering of the value itself. For a container, use Python `repr()` of the whole container in its runtime iteration order; do not separately serialize, sort, or deduplicate its elements. Thus strings retain their Python quotes, and `None` and `True` use Python spellings (for example, the unrelated value `["sample", None]` would be represented by the JSON string `"['sample', None]"`). Embedded newline characters are real newline characters in the represented value and are escaped only as required when that string is encoded in JSON. The local exists at every observation point, so JSON `null`, an empty string, and an omitted array entry are not substitutes for a missing value. The only output key is `temporal_value_history`, and every array entry is a JSON string."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_event(line: str) -> dict[str, object] | None:
    match = re.match(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} "
        r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
        r"event=(?P<event>\w+).* locals=(?P<locals>\{.*\})$",
        line,
    )
    if match is None:
        return None

    try:
        local_changes = ast.literal_eval(match.group("locals"))
    except (SyntaxError, ValueError) as error:
        fail(f"could not parse locals from trace line: {error}")

    if not isinstance(local_changes, dict):
        fail("trace locals payload is not a dictionary")

    return {
        "file": match.group("file").replace("\\", "/"),
        "line": int(match.group("line")),
        "func": match.group("func"),
        "event": match.group("event"),
        "locals": local_changes,
    }


def harvest(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in raw.splitlines():
        event = parse_event(raw_line)
        if (
            event is not None
            and str(event["file"]).endswith(TARGET_FILE)
            and event["func"] == TARGET_FUNC
        ):
            events.append(event)

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    current_locals: dict[str, str] = {}
    awaiting_post_line_state = False
    history: list[str] = []

    for event in events:
        event_kind = str(event["event"])
        if event_kind == "call":
            if awaiting_post_line_state:
                fail(f"line {OBSERVED_LINE} did not complete in its invocation")
            current_locals = {}

        changes = event["locals"]
        if not isinstance(changes, dict):
            fail("parsed locals payload changed type unexpectedly")
        current_locals.update(changes)

        if awaiting_post_line_state:
            if event_kind != "line":
                fail(f"line {OBSERVED_LINE} did not complete normally")
            if "flashes" not in current_locals:
                fail("observation is missing the local 'flashes'")
            history.append(current_locals["flashes"])
            awaiting_post_line_state = False

        if event_kind == "line" and event["line"] == OBSERVED_LINE:
            awaiting_post_line_state = True

        if event_kind == "return":
            current_locals = {}

    if awaiting_post_line_state:
        fail(f"trace ended before line {OBSERVED_LINE} completed")
    if not history:
        fail(f"found no successful executions of line {OBSERVED_LINE}")

    return {"temporal_value_history": history}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"temporal_value_history": ["str"]},
        "oracle_answer": harvest(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
