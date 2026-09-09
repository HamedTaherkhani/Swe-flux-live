#!/usr/bin/env python3
import argparse
import builtins
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/click/decorators.py"
TARGET_FUNC = "click.decorators.command.<locals>.decorator"
EVENT_RE = re.compile(
    r" (?P<file>\S*src/click/decorators\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)(?: |$)"
)
EXCEPTION_RE = re.compile(r" exc=(?P<type>[^: ]+): .* locals=")

QUESTION = """Run every pytest-collected test method whose name begins with `test_` in `DecoratorsDecoratorExceptionTests` from `click_qa/decorators_decorator_m5_exceptions/files/testcase.py`, and aggregate the result over all of those methods. For this run, report per-type counts of exceptions observed in the exact target frame `click.decorators.command.<locals>.decorator` (the nested source function `command.decorator`) in repo-relative file `src/click/decorators.py`.

An exception is observed once when execution of that exact target frame receives an exception event: this includes an exception raised by code in the frame and an exception propagating into it from any callee. An exception raised and fully handled inside a callee before control returns to the target does not count. An exception raised in the target and then handled there does count. If the same exception object is raised or re-raised again later in the same target-frame invocation, count every such target-frame observation separately. An invocation is one call of the target function during the complete pytest run; invocations are 1-based in chronological execution order, although invocation numbers are not included in the answer.

Counts are totals over all invocations and all test methods, so repeated observations of one type in one or many methods all contribute separately. Name exception types using bare `type(exc).__name__` for built-ins (for example, `BufferError`, never `builtins.BufferError`) and `module.QualName` for all others. Message = exact `str(exc)`; messages are not included in this answer.

Return one JSON object with exactly the key `exception_type_counts`. Its value is a list of objects, each with exactly `count` (a JSON integer) and `exception_type` (a JSON string). Include every type observed at least once, aggregate duplicate type names into one object, and do not deduplicate observations before counting. Sort the list by `exception_type` in ascending Unicode code-point order. Aggregation guarantees at most one object per type, so no tie remains; if equal names arise before aggregation, combine their counts before sorting."""


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalized_type(raw_name):
    candidate = getattr(builtins, raw_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__
    fail(
        "trace contains a non-built-in exception without enough module "
        f"information to normalize it: {raw_name!r}"
    )


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    counts = Counter()

    for raw_line in text.splitlines():
        event_match = EVENT_RE.search(raw_line)
        if event_match is None:
            continue
        if event_match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        if event_match.group("event") != "exception":
            continue

        exception_match = EXCEPTION_RE.search(raw_line)
        if exception_match is None:
            fail(f"malformed target exception event: {raw_line}")
        counts[normalized_type(exception_match.group("type"))] += 1

    if target_events == 0:
        fail(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not counts:
        fail(f"trace contains no exception events for {TARGET_FUNC}")

    answer = {
        "exception_type_counts": [
            {"count": counts[name], "exception_type": name}
            for name in sorted(counts)
        ]
    }
    payload = {
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
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
