#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "/src/flask/testing.py"
TARGET_FUNC = "flask.testing.FlaskClient.open"
EVENT_RE = re.compile(
    r"^(?:.*?)" + re.escape(TARGET_FILE) + r":(?P<line>\d+) "
    + re.escape(TARGET_FUNC)
    + r" event=(?P<event>call|line|return|exception)\b.*? locals=(?P<locals>\{.*\})$"
)


def parse_locals(text, source_line):
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as error:
        raise SystemExit(
            f"ERROR: cannot parse target locals on trace line {source_line}: {text!r}"
        ) from error

    if not isinstance(value, dict):
        raise SystemExit(
            f"ERROR: target locals are not a dictionary on trace line {source_line}"
        )
    return value


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")

    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    target_events = []

    for source_line, raw_line in enumerate(trace_text.splitlines(), start=1):
        match = EVENT_RE.match(raw_line)

        if match is not None:
            target_events.append(
                (
                    match.group("event"),
                    int(match.group("line")),
                    parse_locals(match.group("locals"), source_line),
                )
            )

    if not target_events:
        raise SystemExit(
            f"ERROR: trace contains zero events for target function {TARGET_FUNC}"
        )

    line_events = [event for event in target_events if event[0] == "line"]
    if len(line_events) < 60:
        raise SystemExit(
            f"ERROR: expected at least 60 target line events, found {len(line_events)}"
        )

    request_reprs = {
        event_locals["request"]
        for _, _, event_locals in line_events
        if "request" in event_locals
    }
    if len(request_reprs) < 8:
        raise SystemExit(
            "ERROR: expected at least 8 distinct observed repr values for "
            f"'request', found {len(request_reprs)}"
        )

    question = (
        "Run the pytest test "
        "`flask_qa/testing_open_m3_state/files/testcase.py::"
        "TestOpenProgramState::test_generated_request_forms` from the repository "
        "root. During that run, consider every invocation of `FlaskClient.open` "
        "(runtime qualified name `flask.testing.FlaskClient.open`) whose frame "
        "executes code in `src/flask/testing.py`. An invocation means one entry "
        "into that function, numbered 1-based in chronological entry order; include "
        "all such invocations made by the test. Within each invocation, observe the "
        "local variable `request` immediately before every executable source line "
        "reached after `request` has first been bound and through the final executed "
        "line in that frame. An observation point is the state immediately before "
        "Python executes that line. Source line numbers, if used to reproduce the "
        "observations, are absolute 1-based lines in the named repository file. For "
        "a multi-line statement or expression, associate execution with the line "
        "where that statement or expression begins. The function's `def` signature, "
        "decorators, comments, and docstring are not observation points. At every "
        "observation point take exact Python `repr(request)`; this means the repr of "
        "the whole request object, not `str(request)`, and Python spellings such as "
        "`None` and `True` would be retained if present. Combine observations from "
        "all invocations, remove duplicate strings by exact equality, then sort the "
        "remaining strings in ascending lexicographic order by Unicode code point "
        "(Python's ordinary ascending string order, with no secondary tie-breaker "
        "because duplicates were removed). Return a JSON object with exactly one "
        "key, `unique_values`, whose value is the sorted array of strings. Do not "
        "use JSON null or an omitted key as a sentinel; an empty repr, if one "
        "occurred, would be represented by the corresponding repr string."
    )

    result = {
        "question_kind": "M3_ProgramState",
        "question": question,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": sorted(request_reprs)},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
