from __future__ import annotations

import argparse
import builtins
import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FUNC = "scrapy.pipelines.files.FilesPipeline.media_downloaded"
EVENT_RE = re.compile(
    r"\s(?P<file>\S*scrapy/pipelines/files\.py):(?P<line>\d+) "
    r"scrapy\.pipelines\.files\.FilesPipeline\.media_downloaded "
    r"event=(?P<event>call|line|return|exception)\b"
    r"(?: exc=(?P<exception_type>[^:\s]+): [^\n]*?)?"
    r"(?= locals=|$)"
)

QUESTION = (
    "Run every pytest-collected `test_*` method in "
    "`scrapy_qa/files_media_downloaded_m5_exceptions/files/testcase.py::"
    "TestFilesMediaDownloaded` and aggregate the complete run. Across every "
    "invocation of `scrapy.pipelines.files.FilesPipeline.media_downloaded` in "
    "`scrapy/pipelines/files.py`, how many target-frame observations are there "
    "of each concrete exception type? An invocation is one call of that exact "
    "function, numbered 1-based in chronological execution order, including "
    "calls that return normally and calls that terminate by exception. An "
    "exception is observed in the target frame each time a statement in that "
    "exact frame raises it, or a direct callee or awaited operation propagates "
    "it into that frame at its call or await site; count one observation each "
    "time the exception becomes active there. This includes the implicit "
    "`StopIteration` delivered to the target frame by Python's await protocol "
    "when an awaited coroutine returns normally, even though the target then "
    "continues execution. An exception raised and fully handled inside a callee "
    "does not count. A bare re-raise in the target frame does not count as "
    "another observation when it re-raises the same exception object already "
    "observed after propagation from a callee. Counts are totals over all "
    "invocations and all test methods, so the same type observed in five "
    "methods contributes five observations. Name exception "
    "types using bare `type(exc).__name__` for built-ins (e.g. `ValueError`, "
    "never `builtins.ValueError`), `module.QualName` for all others. Here "
    "`module.QualName` means "
    "`type(exc).__module__ + \".\" + type(exc).__qualname__` (for example, "
    "`package.errors.CustomError`). Message = exact `str(exc)`, although "
    "messages are not included in this answer and do not split a type into "
    "multiple groups. Return exactly one JSON object with key "
    "`exception_type_counts`; its value is a JSON array of objects, each with "
    "exactly `count` (a JSON integer) and `exception_type` (a JSON string). "
    "Include every type observed at least once, preserve multiplicity in its "
    "count, and aggregate duplicate type names into one object. Sort objects by "
    "`exception_type` in ascending lexicographic Unicode code-point order. "
    "Equal type names are aggregated before sorting, so no tie remains and no "
    "secondary tie-breaker is applicable."
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def exception_name_registry() -> dict[str, str]:
    classes: list[type[BaseException]] = []
    for value in vars(builtins).values():
        if isinstance(value, type) and issubclass(value, BaseException):
            classes.append(value)

    module = importlib.import_module("scrapy.pipelines.files")
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, BaseException):
            classes.append(value)

    candidates: dict[str, set[str]] = {}
    for exception_class in classes:
        if exception_class.__module__ == "builtins":
            qualified = exception_class.__name__
        else:
            qualified = (
                f"{exception_class.__module__}.{exception_class.__qualname__}"
            )
        candidates.setdefault(exception_class.__name__, set()).add(qualified)

    registry: dict[str, str] = {}
    for short_name, qualified_names in candidates.items():
        if len(qualified_names) == 1:
            registry[short_name] = next(iter(qualified_names))
    return registry


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    try:
        trace_text = trace_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read trace log {trace_path}: {exc}")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = [match.groupdict() for match in EVENT_RE.finditer(trace_text)]
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    exception_events = [
        event for event in events if event["event"] == "exception"
    ]
    if not exception_events:
        fail(f"trace contains zero exception events for {TARGET_FUNC}")
    if any(not event["exception_type"] for event in exception_events):
        fail("an exception event is missing its exception type")

    registry = exception_name_registry()
    counts: Counter[str] = Counter()
    for event in exception_events:
        short_name = event["exception_type"]
        if short_name not in registry:
            fail(f"cannot resolve exception type name {short_name!r}")
        counts[registry[short_name]] += 1

    answer = {
        "exception_type_counts": [
            {"count": counts[exception_type], "exception_type": exception_type}
            for exception_type in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [
                {"count": "int", "exception_type": "str"}
            ]
        },
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
