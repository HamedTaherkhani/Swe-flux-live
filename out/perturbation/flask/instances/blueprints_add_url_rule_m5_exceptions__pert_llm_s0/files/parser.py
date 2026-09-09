#!/usr/bin/env python3
import argparse
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "src/flask/sansio/blueprints.py"
TARGET_FUNC = "flask.sansio.blueprints.Blueprint.add_url_rule"

QUESTION = (
    "Run only the pytest test `flask_qa/blueprints_add_url_rule_m5_exceptions/"
    "files/testcase.py::BlueprintRouteExceptionTest::"
    "test_generated_route_registrations`. Test identifiers use pytest's exact "
    "`repo-relative-file::Class::method` id format, for example "
    "`pkg/test_sample.py::SampleCase::test_behavior`. During that entire test "
    "run, consider every invocation of exactly "
    "`flask.sansio.blueprints.Blueprint.add_url_rule` whose frame is defined "
    "in the repo-relative file `src/flask/sansio/blueprints.py`. An invocation "
    "means one runtime call of that exact function, numbered 1-based in "
    "chronological order. For all such invocations, collect the exception "
    "types from Python runtime exception events emitted by the target "
    "function's own frame. Such an event counts whether the exception is "
    "raised directly by the target or propagates into the target frame from a "
    "callee. Do not count exceptions in decorators, callers, callees, nested "
    "functions, or any other frame unless propagation also produces an "
    "exception event in the exact target frame. Count all target invocations, "
    "including invocations that return normally, but a normal return adds no "
    "type. Name each exception type using bare `type(exc).__name__` for "
    "built-ins (for example, `KeyError`, never `builtins.KeyError`) and "
    "`module.QualName` for all others, formed as "
    "`type(exc).__module__ + \".\" + type(exc).__qualname__` (for example, "
    "`sample.errors.WidgetFault`). Exception messages are not reported; if "
    "they were needed, message would mean exact `str(exc)`. Remove duplicate "
    "type-name strings across events and invocations, then sort the remaining "
    "strings in ascending lexicographic order by Unicode code point; there is "
    "no chronological tie-breaker after deduplication. Return exactly one JSON "
    "object with the sole key `exception_types`; its value is the sorted JSON "
    "array of strings. The strings are type names in the stated format, not "
    "`repr()` or `str()` of exception instances, and no empty or null "
    "placeholder is inserted for successful invocations."
)

EVENT_RE = re.compile(
    r"(?P<file>\S*src/flask/sansio/blueprints\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    r"(?:\s+exc=(?P<exc_type>[^:\s]+):)?"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def normalize_exception_type(raw_name: str) -> str:
    candidate = getattr(builtins, raw_name, None)

    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__

    if "." in raw_name:
        return raw_name

    fail(
        "trace contains a non-built-in exception without a module-qualified "
        f"name: {raw_name}"
    )


def parse_trace(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")

    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events: list[tuple[str, str | None]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)

        if match is None:
            continue

        file_name = match.group("file").replace("\\", "/")

        if not file_name.endswith(TARGET_FILE):
            continue

        if match.group("func") != TARGET_FUNC:
            continue

        target_events.append((match.group("event"), match.group("exc_type")))

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    call_count = sum(event == "call" for event, _ in target_events)

    if call_count == 0:
        fail("target trace contains no call events")

    raw_exception_types = [
        exc_type
        for event, exc_type in target_events
        if event == "exception" and exc_type is not None
    ]

    if not raw_exception_types:
        fail("target trace contains no parseable exception events")

    return sorted(
        {normalize_exception_type(exc_type) for exc_type in raw_exception_types}
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    exception_types = parse_trace(args.trace_log)
    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": {"exception_types": exception_types},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
