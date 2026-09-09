#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/cli.py"
TARGET_FUNC = "flask.cli.find_app_by_string"
OBSERVED_LINE = 178
OCCURRENCE = 17
VARIABLES = ("app", "args", "kwargs", "name")

QUESTION = """Run the pytest test `flask_qa/cli_find_app_by_string_s3_state/files/testcase.py::TestComputedFactoryImports::test_loads_generated_factory_expressions`. During that test run, consider only execution of `flask.cli.find_app_by_string` in `src/flask/cli.py`. What are the values of the local variables `app`, `args`, `kwargs`, and `name` immediately after line 178 has executed successfully for the 17th time?

Line numbers are absolute, 1-based line numbers in `src/flask/cli.py` as it exists in the repository. For a multi-line statement or expression, its executed line is the line on which that statement or expression begins; the function's `def` line, decorator lines, and docstring lines do not count unless Python executes them as line events in the function frame. Here, “the 17th time” means the 17th chronological successful completion of the statement beginning on line 178 across the entire test run, counting only this exact target function. An invocation is one call of this function, numbered from 1 in chronological order. Do not include executions or locals from callers, callees, comprehension frames, or any other function.

Return exactly one JSON object with the shape `{"observed_state": [{"value": "...", "variable": "..."}]}`. Include exactly one entry for each of the four named variables, ordered by `variable` in ascending Unicode code-point order; do not deduplicate entries. Each `variable` is the bare local-variable name. Each `value` is the full Python `repr()` string of that local's concrete value at the observation point, not `str()` and not a JSON rendering of the value itself. For a container, use the `repr()` of the whole container rather than separately serializing its elements. Thus strings retain their Python quotes, and `None` and `True` use Python spellings (for example, the unrelated value `["x", None]` would be represented by the JSON string `"['x', None]"`). Embedded newline characters are represented as real newline characters inside the JSON string, subject to normal JSON escaping. All four locals exist at this point, so do not use JSON `null`, an empty string, or an omitted entry to represent a missing value. The only output keys are `observed_state`, `value`, and `variable`; `observed_state` is a JSON array and both fields in each entry are JSON strings."""


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


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
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
    completed_occurrences = 0
    awaiting_post_line_state = False
    observed: dict[str, str] | None = None

    for event in events:
        event_kind = str(event["event"])
        if event_kind == "call":
            current_locals = {}
            awaiting_post_line_state = False

        changes = event["locals"]
        if not isinstance(changes, dict):
            fail("parsed locals payload changed type unexpectedly")
        current_locals.update(changes)

        if awaiting_post_line_state:
            if event_kind != "line":
                fail(
                    f"line {OBSERVED_LINE} did not complete normally at "
                    f"occurrence {OCCURRENCE}"
                )
            observed = dict(current_locals)
            break

        if event_kind == "line" and event["line"] == OBSERVED_LINE:
            completed_occurrences += 1
            if completed_occurrences == OCCURRENCE:
                awaiting_post_line_state = True

        if event_kind == "return":
            current_locals = {}

    if observed is None:
        fail(
            f"did not observe completed occurrence {OCCURRENCE} "
            f"of line {OBSERVED_LINE}"
        )

    missing = sorted(set(VARIABLES) - observed.keys())
    if missing:
        fail(f"observation is missing required locals: {missing}")

    return {
        "observed_state": [
            {"value": observed[variable], "variable": variable}
            for variable in sorted(VARIABLES)
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
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
