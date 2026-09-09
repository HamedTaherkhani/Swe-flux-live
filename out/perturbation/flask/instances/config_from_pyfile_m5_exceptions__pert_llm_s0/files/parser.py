#!/usr/bin/env python3
import argparse
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.config.Config.from_pyfile"

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/flask/config\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?: exc=(?P<exc_type>[^:\s]+):.*?)? locals="
)

QUESTION = """Run the pytest test
`flask_qa/config_from_pyfile_m5_exceptions/files/testcase.py::TestConfigEnvironmentLoads::test_generated_configuration_matrix`
against this repository. Across the complete run of that named test, what
distinct exception types reach the active frame of the exact target function
`flask.config.Config.from_pyfile` in `src/flask/config.py`?

An exception reaches the target frame when evaluating a statement in that
frame, including a call made by that statement, transfers exception control
to the target frame. Include every such event from the target's body,
regardless of whether the target catches it and continues or returns, or
whether it ultimately propagates out of the target. Thus, include exceptions
from operations called by the target only when they propagate back into the
target frame. Exclude exceptions handled wholly inside a callee, exceptions
that occur only in a caller after the target has exited, and events in any
other function or frame. Include all target invocations, both successful and
raising: an invocation is one call of the exact target function during the
named test, numbered 1-based in chronological call order. Invocation numbers
are not reported.

Deduplicate by the final exception-type string across all invocations, even
when the same type reaches the frame multiple times or at different source
lines. Sort the deduplicated strings in ascending lexicographic order by
Unicode code point using ordinary Python string ordering; after
deduplication there are no ordering ties.

Exception type naming MUST use this convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError`, never `builtins.ValueError`), and
`module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`). Exception messages and values are not
reported, so no `str`, `repr`, empty-string, or JSON-null serialization rule
applies to them.

Return exactly one JSON object with the single key `exception_types`. Its
value must be a JSON list of strings ordered as specified above."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_exception_type(raw_name: str) -> str:
    value = getattr(builtins, raw_name, None)
    if isinstance(value, type) and issubclass(value, BaseException):
        return value.__name__
    fail(
        "encountered a non-built-in exception type whose module and qualname "
        f"are unavailable in the trace: {raw_name}"
    )


def parse_trace(trace_path: Path) -> list[str]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    exception_types: set[str] = set()

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None or match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            if match.group("event") != "exception":
                continue

            raw_name = match.group("exc_type")
            if not raw_name:
                fail("target exception event has no parseable exception type")
            exception_types.add(normalize_exception_type(raw_name))

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not exception_types:
        fail(f"trace contains no exception events for {TARGET_FUNC}")

    return sorted(exception_types)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": {"exception_types": parse_trace(args.trace_log)},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
