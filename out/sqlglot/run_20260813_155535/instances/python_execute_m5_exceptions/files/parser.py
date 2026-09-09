import argparse
import builtins
import importlib
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "sqlglot/executor/python.py"
TARGET_FUNC = "sqlglot.executor.python.PythonExecutor.execute"
EVENT_RE = re.compile(
    r"(?P<path>\S*sqlglot/executor/python\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<exception_type>[^:\s]+): ")

QUESTION = """Run pytest on every test method in class
`TestPythonExecuteExceptions` in
`sqlglot_qa/python_execute_m5_exceptions/files/testcase.py` and aggregate the
results over all of those methods. The covered methods are exactly every method
in that class whose name starts with `test_`; an individual pytest id has the
form
`sqlglot_qa/python_execute_m5_exceptions/files/testcase.py::TestPythonExecuteExceptions::test_safe_long_dependency_chain`.
The answer is independent of pytest's method execution order because it consists
of commutative totals over the complete class.

For the exact frame of
`sqlglot.executor.python.PythonExecutor.execute` in
`sqlglot/executor/python.py`, how many exception observations of each type occur
during the complete run?

An exception observation occurs whenever code in that exact target frame raises
an exception or an exception propagates into that frame from a callee. Count one
observation for each such event in the target frame, including an exception that
the target subsequently catches. An exception raised and fully handled inside a
callee does not count because it never propagates into the target frame. If the
same exception object is re-raised in the target frame, count that re-raise as a
new observation. Do not deduplicate observations by exception identity, source
line, invocation, or test method.

Exception type naming MUST use the same convention as S5, stated verbatim: bare
`type(exc).__name__` for built-ins (e.g. `ValueError`, never
`builtins.ValueError`), `module.QualName` for all others. For non-built-ins,
`module.QualName` is exactly
`f"{type(exc).__module__}.{type(exc).__qualname__}"` (for example,
`package.WidgetError`). Message = exact `str(exc)`, although exception messages
are not fields in this answer.

An invocation is one `call` of the target function during the test run,
numbered 1-based in chronological order. Counts are totals over ALL invocations
and ALL test methods, so the same type observed in five methods contributes five
to its total.

Return exactly
`{"exception_type_counts": [{"count": <JSON integer>, "exception_type": <JSON string>}, ...]}`.
Include one row for every exception type observed at least once. Merge rows with
the same exact formatted `exception_type` by summing their counts; preserve all
multiplicity in those totals and perform no other deduplication. Sort rows by
`exception_type` ascending using Python string Unicode code-point order. After
merging there is exactly one row for each type string, so equal primary keys
cannot remain and there is no secondary tie-break."""


def exception_type_name(raw_name):
    builtin = getattr(builtins, raw_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return builtin.__name__

    target_module = importlib.import_module("sqlglot.executor.python")
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
    for line_number, line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), 1
    ):
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
