import argparse
import builtins
import importlib
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/expressions/builders.py"
TARGET_FUNC = "sqlglot.expressions.builders.to_table"
EVENT_RE = re.compile(
    r"(?P<path>\S*sqlglot/expressions/builders\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<exception_type>[^:\s]+): ")

QUESTION = """Run pytest on every test method in class `TestToTableExceptions` in
`sqlglot_qa/builders_to_table_m5_exceptions/files/testcase.py`, and aggregate the
results over all those methods. The covered methods are exactly every method in
that class whose name starts with `test_`; their pytest ids have the form
`sqlglot_qa/builders_to_table_m5_exceptions/files/testcase.py::TestToTableExceptions::test_generated_qualified_names`.
The answer is independent of pytest's method execution order because it contains
commutative totals over the whole class.

For `sqlglot.expressions.builders.to_table` in
`sqlglot/expressions/builders.py`, how many exception observations of each type
occur in that exact function frame during the complete run?

An exception observation occurs whenever execution in that exact `to_table`
frame raises an exception itself or receives an exception propagated from a
callee. Count one observation each time this happens in the target frame,
including an exception that the target subsequently catches. An exception
raised and fully handled inside a callee does not count because it never
propagates into the target frame. If the same exception object is re-raised in
the target frame, count the re-raise as another observation; observations are
not deduplicated by object identity, line, invocation, or test method.

Exception type naming uses bare `type(exc).__name__` for built-ins (e.g.
`ValueError`, never `builtins.ValueError`), `module.QualName` for all others.
Here `module.QualName` means
`f"{type(exc).__module__}.{type(exc).__qualname__}"`. Message = exact
`str(exc)`, although messages are not included in this answer shape.

An invocation is one call of the target function, numbered 1-based in
chronological order within the complete pytest run. Counts are totals over all
invocations and all test methods, so repeated observations of one type in five
methods contribute five to that type's total.

Return exactly
`{"exception_type_counts": [{"count": <JSON integer>, "exception_type": <JSON string>}, ...]}`.
Emit one row for every exception type observed at least once. Merge observations
having the same exact formatted exception type by summing their counts; do not
otherwise remove duplicates. Sort rows by `exception_type` ascending using
Python string (Unicode code-point) order. Because merging leaves one row per
exact type string, equal sort keys cannot remain and no secondary tie-break is
applicable."""


def exception_type_name(raw_name):
    builtin = getattr(builtins, raw_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return builtin.__name__

    target_module = importlib.import_module("sqlglot.expressions.builders")
    candidates = {
        f"{value.__module__}.{value.__qualname__}"
        for value in vars(target_module).values()
        if isinstance(value, type)
        and issubclass(value, BaseException)
        and value.__name__ == raw_name
    }
    if len(candidates) != 1:
        raise RuntimeError(
            f"cannot uniquely resolve non-built-in exception type {raw_name!r}: "
            f"{sorted(candidates)!r}"
        )
    return candidates.pop()


def parse_trace(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if not trace_path.is_file() or trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    counts = Counter()
    for line_number, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        match = EVENT_RE.search(line)
        if not match or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        if match.group("event") != "exception":
            continue

        exception_match = EXCEPTION_RE.search(line)
        if not exception_match:
            raise RuntimeError(
                f"malformed target exception event at trace line {line_number}"
            )
        counts[exception_type_name(exception_match.group("exception_type"))] += 1

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not counts:
        raise RuntimeError(f"trace contains zero exception events for {TARGET_FUNC}")

    return {
        "exception_type_counts": [
            {"count": count, "exception_type": exception_type}
            for exception_type, count in sorted(counts.items())
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [{"count": "int", "exception_type": "str"}]
        },
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
