#!/usr/bin/env python3
import argparse
import builtins
import json
from pathlib import Path
import re
import sys

import jinja2.exceptions


TARGET_FILE = "src/flask/templating.py"
TARGET_FUNC = "flask.templating.DispatchingJinjaLoader._get_source_explained"

QUESTION = """Run the pytest test `flask_qa/templating_get_source_explained_m5_exceptions/files/testcase.py::TestGeneratedExplainedLoadingExceptions::test_generated_loader_outcomes`. Across the complete run of that one test, what distinct exception types occur in the own frame of `flask.templating.DispatchingJinjaLoader._get_source_explained` in `src/flask/templating.py`?

An invocation is one call of that exact function, counted 1-based in chronological runtime-event order across the whole test. An exception occurrence counts whenever CPython reports an `exception` event in the target function's own active frame: include exceptions raised directly by the target, exceptions propagated into that frame by `loader.get_source` or another callee, and exceptions that the target subsequently catches as well as those that leave the invocation uncaught. Count only the occurrence in the target frame; exclude occurrences reported only in callers, callees, `_iter_loaders`' generator frame, comprehensions, or any other frame. Do not infer an occurrence merely from a returned value or from an exception handled entirely inside a callee.

Normalize each occurrence's exception class using this convention: bare `type(exc).__name__` for built-ins (e.g. `ValueError`, never `builtins.ValueError`), `module.QualName` for all others. Here `module` is `type(exc).__module__` and `QualName` is `type(exc).__qualname__`, joined by one dot. Use the actual exception object at the occurrence; do not use its message, `str()`, or `repr()`.

Process qualifying exception occurrences in chronological runtime-event order across all invocations, with their actual event-stream order as the tie-breaker if clock readings are equal. Deduplicate after name normalization: retain each normalized type string only at its first occurrence and omit every later duplicate. Thus the result is first-occurrence order, not alphabetical order.

Return exactly one JSON object with the canonical shape `{"exception_types": ["str"]}`. The `exception_types` value is a JSON array of the normalized JSON strings in the order defined above; `"str"` in the displayed shape is a type placeholder, not a literal result. Emit no exception messages, invocation numbers, nulls, or additional keys."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_event(raw_line: str) -> dict[str, str] | None:
    match = re.match(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} "
        r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
        r"event=(?P<event>\w+)(?: exc=(?P<exc>.+?) locals=| )",
        raw_line,
    )
    if match is None:
        return None
    return {
        "file": match.group("file").replace("\\", "/"),
        "func": match.group("func"),
        "event": match.group("event"),
        "exc": match.group("exc") or "",
    }


def normalize_exception_type(exc_field: str) -> str:
    match = re.match(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*): ", exc_field)
    if match is None:
        fail(f"cannot parse exception field: {exc_field!r}")
    name = match.group("name")

    candidate = getattr(builtins, name, None)
    if (
        isinstance(candidate, type)
        and issubclass(candidate, BaseException)
        and candidate.__module__ == "builtins"
    ):
        return candidate.__name__

    matches = []
    for candidate in vars(jinja2.exceptions).values():
        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseException)
            and candidate.__name__ == name
        ):
            matches.append(candidate)
    unique_matches = {
        (candidate.__module__, candidate.__qualname__): candidate
        for candidate in matches
    }
    if len(unique_matches) != 1:
        fail(
            f"cannot uniquely resolve non-built-in exception type {name!r}; "
            f"found {sorted(unique_matches)}"
        )
    module, qualname = next(iter(unique_matches))
    return f"{module}.{qualname}"


def harvest(trace_path: Path) -> dict[str, list[str]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in raw.splitlines():
        event = parse_event(raw_line)
        if (
            event is not None
            and event["file"].endswith(TARGET_FILE)
            and event["func"] == TARGET_FUNC
        ):
            target_events.append(event)
    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    exception_fields = [
        event["exc"] for event in target_events if event["event"] == "exception"
    ]
    if not exception_fields:
        fail(f"trace contains zero exception events for {TARGET_FUNC}")

    exception_types = []
    seen = set()
    for exc_field in exception_fields:
        normalized = normalize_exception_type(exc_field)
        if normalized not in seen:
            seen.add(normalized)
            exception_types.append(normalized)

    if len(exception_fields) < 3:
        fail(f"trace contains only {len(exception_fields)} target exception events")
    if len(exception_types) < 2:
        fail("trace contains fewer than two distinct normalized exception types")
    return {"exception_types": exception_types}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
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
