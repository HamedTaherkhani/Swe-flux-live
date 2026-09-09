import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_NAME = "flask.app.Flask.url_for"
OBSERVATION_LINE = 1220
FOLLOWING_LINE = 1222
OBSERVATION_ORDINAL = 17
VARIABLES = ("_anchor", "endpoint", "rv", "values")

QUESTION = """Run the pytest test `flask_qa/app_url_for_s3_state/files/testcase.py::TestAppUrlForProgramState::test_computed_blueprint_urls`. During that complete test run, consider only executions in `flask.app.Flask.url_for` as defined in the repository-relative file `src/flask/app.py`. What are the values of the four local variables `_anchor`, `endpoint`, `rv`, and `values` immediately after absolute line 1220 has executed for the 17th time during the test run?

Line numbers are absolute, 1-based source line numbers in `src/flask/app.py` as it exists in the repository. Count executions of line 1220 in chronological order across all invocations of this target function, starting at 1; an invocation is one Python call of `flask.app.Flask.url_for`. Here, executing line 1220 means completing the assignment statement that begins on that line. The observation point is after that assignment has completed and before the return statement on line 1222 executes. No executions in any other function count.

Return a JSON object with exactly one key, `observed_state`. Its value must be a list of exactly four objects, each with exactly the keys `value` and `variable`. Order the objects by `variable` in ascending Python string (Unicode code-point) order; do not deduplicate them. The `variable` value is the local variable's name as a JSON string. The `value` value is a JSON string containing Python `repr()` of that local's value at the observation point. For a container, use `repr()` of the whole container in its runtime iteration/insertion order, without recursively sorting it. Thus strings inside repr values retain their Python quotes, and `None`, `True`, and `False` use Python spellings. If a repr contains a newline, it is a newline character in the decoded JSON string (escaped as required by JSON syntax in serialized JSON). All four named locals exist at this point, so do not omit an object or substitute JSON `null` or an empty string."""


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_event(line):
    if "src/flask/app.py:" not in line or f" {TARGET_NAME} event=" not in line:
        return None

    try:
        prefix, locals_text = line.rsplit(" locals=", 1)
        locals_delta = ast.literal_eval(locals_text)
    except (ValueError, SyntaxError) as exc:
        fail(f"could not parse target locals: {exc}")

    match = re.search(
        rf"src/flask/app\.py:(\d+) {re.escape(TARGET_NAME)} event=(\w+)",
        prefix,
    )
    if match is None:
        fail(f"malformed target event line: {line.rstrip()}")
    if not isinstance(locals_delta, dict):
        fail("target event locals payload is not a dictionary")

    return int(match.group(1)), match.group(2), locals_delta


def harvest(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    line_count = 0
    current_locals = None
    observed = None
    awaiting_following_line = False

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            event = parse_event(raw_line)
            if event is None:
                continue

            target_events += 1
            lineno, event_name, locals_delta = event

            if event_name == "call":
                current_locals = {}
                awaiting_following_line = False

            if current_locals is None:
                fail("encountered a target event before its call event")
            current_locals.update(locals_delta)

            if event_name == "line" and lineno == OBSERVATION_LINE:
                line_count += 1
                awaiting_following_line = line_count == OBSERVATION_ORDINAL
                continue

            if (
                awaiting_following_line
                and event_name == "line"
                and lineno == FOLLOWING_LINE
            ):
                missing = [name for name in VARIABLES if name not in current_locals]
                if missing:
                    fail(f"observation is missing locals: {missing}")
                observed = {name: current_locals[name] for name in VARIABLES}
                awaiting_following_line = False

            if event_name == "return":
                if awaiting_following_line:
                    fail("target returned before the observation could be captured")
                current_locals = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_NAME}")
    if observed is None:
        fail(
            f"line {OBSERVATION_LINE} executed only {line_count} times; "
            f"needed {OBSERVATION_ORDINAL}"
        )

    return {
        "observed_state": [
            {"value": observed[name], "variable": name}
            for name in sorted(VARIABLES)
        ]
    }


def main():
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
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")

    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
