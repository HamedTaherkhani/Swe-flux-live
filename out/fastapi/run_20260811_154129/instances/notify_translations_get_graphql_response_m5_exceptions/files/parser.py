#!/usr/bin/env python3
import argparse
import builtins
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/notify_translations.py"
TARGET_FUNC = "scripts.notify_translations.get_graphql_response"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(
    r"\bevent=exception exc=(?P<type>[A-Za-z_][A-Za-z0-9_]*): .*? locals="
)

QUESTION = """Run exactly this pytest test against the repository:
`fastapi_qa/notify_translations_get_graphql_response_m5_exceptions/files/testcase.py::TestGraphQLResponseFailures::test_generated_response_matrix`.
Pytest ids in this question use the repo-relative
`path/to/test_file.py::TestClass::test_method` format (for example,
`tests/test_demo.py::TestDemo::test_case`).

Across the entire test run, consider every invocation of
`scripts.notify_translations.get_graphql_response`, defined in
`scripts/notify_translations.py`. An invocation means one entry into exactly
that function's frame, numbered 1-based in chronological call-entry order.
Frames belonging to callers, callees, properties, comprehensions, or
generators are not target invocations.

Report the distinct exception types observed in the target frame. An exception
is observed when it is raised by code executing in that exact target frame or
when a callee's exception propagates into that frame. Count the target-frame
observation once; do not separately count observations in callee or caller
frames. Exceptions raised and fully handled inside a callee do not count.
Invocations that return normally contribute no exception type.

Use this exception type naming convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError`, never `builtins.ValueError`),
`module.QualName` for all others. Preserve chronological order across target
invocations and within each invocation, then remove duplicates globally by
the fully formatted type name, retaining only each name's first occurrence.
Do not alphabetically sort the result.

Return exactly one JSON object of the form
`{"exception_types": ["str"]}`. `exception_types` is a JSON array of strings;
each string uses the naming convention above. The array must be present even
when no exception is observed (then it is `[]`); no item may be an empty
string or JSON `null`. Exception messages, source lines, invocation numbers,
and counts are not part of the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def format_exception_type(traced_name: str) -> str:
    exception_class = getattr(builtins, traced_name, None)
    if (
        isinstance(exception_class, type)
        and issubclass(exception_class, BaseException)
    ):
        return exception_class.__name__
    fail(
        "trace does not contain enough information to qualify non-built-in "
        f"exception type {traced_name!r}"
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events: list[tuple[str, str]] = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        traced_file = match.group("file").replace("\\", "/")
        if not traced_file.endswith(TARGET_FILE):
            fail(f"target event came from unexpected file: {traced_file}")
        target_events.append((match.group("event"), raw_line))

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    call_count = sum(event == "call" for event, _ in target_events)
    line_count = sum(event == "line" for event, _ in target_events)
    exception_lines = [
        raw_line for event, raw_line in target_events if event == "exception"
    ]
    if call_count == 0:
        fail(f"trace contains no invocations of {TARGET_FUNC}")
    if line_count == 0:
        fail(f"trace contains no executed lines in {TARGET_FUNC}")
    if not exception_lines:
        fail(f"trace contains no target-frame exceptions in {TARGET_FUNC}")

    exception_types = []
    seen = set()
    for raw_line in exception_lines:
        match = EXCEPTION_RE.search(raw_line)
        if match is None:
            fail(f"target exception event has no parseable type: {raw_line}")
        exception_type = format_exception_type(match.group("type"))
        if exception_type not in seen:
            seen.add(exception_type)
            exception_types.append(exception_type)

    output = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": {"exception_types": exception_types},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote layered-exception oracle to {out_path}")


if __name__ == "__main__":
    main()
