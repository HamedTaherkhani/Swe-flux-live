import argparse
import builtins
from collections import Counter
import json
from pathlib import Path
import re


TARGET_FUNC = "sqlglot.dialects.dialect.Dialect.get_or_raise"
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/dialects/dialect\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?P<rest>.*)$"
)
EXCEPTION_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = (
    "Run every test method in the unittest class `TestDialectLookupExceptions` in "
    "`sqlglot_qa/dialect_get_or_raise_m5_exceptions/files/testcase.py` (equivalently, "
    "run the pytest class selector "
    "`sqlglot_qa/dialect_get_or_raise_m5_exceptions/files/testcase.py::"
    "TestDialectLookupExceptions`). Aggregate the answer over ALL `test_...` methods "
    "in that class and over every invocation they make, including methods that finish "
    "without an exception. A test's pytest id has the exact form "
    "`repo/relative/test_file.py::ClassName::test_method`, for example "
    "`tests/test_demo.py::TestExample::test_case`; test ids do not appear in the "
    "requested answer, and test execution order does not affect the aggregation. "
    "For exactly `sqlglot.dialects.dialect.Dialect.get_or_raise` in "
    "`sqlglot/dialects/dialect.py`, report how many exception observations of each "
    "type occur in that exact target frame. An invocation means one Python `call` of "
    "exactly this function, numbered 1-based in chronological order across the run; "
    "nested callees and their frames are not target invocations. An exception is "
    "observed when Python delivers an exception event to the target frame: this "
    "includes an exception raised by code in that frame and one propagated into it "
    "from a callee. Count one observation per such target-frame event. An exception "
    "raised and fully handled inside a callee does not count. If the target catches "
    "an observed exception and later raises another exception, count both events; if "
    "the same exception object is re-raised in the target and Python delivers another "
    "target-frame exception event, count that event again as well. Counts are totals "
    "over ALL invocations and ALL test methods, not counts of distinct objects or "
    "invocations, so a type observed five times contributes a count of five. Report "
    "exception types using this convention: bare `type(exc).__name__` for built-in "
    "exceptions (for example, `ValueError`, never `builtins.ValueError`), "
    "`module.QualName` for all others. Return exactly a JSON object with the key "
    "`exception_type_counts`, whose value is a list of objects; every object has "
    "exactly two string keys: `count`, mapped to an integer, and `exception_type`, "
    "mapped to a string. Group duplicate type names into one object, include every "
    "type observed at least once, and sort the list by `exception_type` ascending "
    "using ordinary Unicode string ordering. There can be only one object per type "
    "after grouping, so no further tie-break is needed; do not deduplicate exception "
    "events before computing each total."
)


def exception_type_name(short_name: str) -> str:
    candidate = getattr(builtins, short_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return short_name
    raise RuntimeError(
        f"cannot derive module-qualified name for non-built-in exception {short_name!r}"
    )


def compute_answer(trace_path: Path) -> dict[str, list[dict[str, int | str]]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            target_events.append(match)

    if not target_events:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not any(match.group("event") == "call" for match in target_events):
        raise RuntimeError(f"trace contains zero calls for {TARGET_FUNC}")

    counts: Counter[str] = Counter()
    for match in target_events:
        if match.group("event") != "exception":
            continue
        exception_match = EXCEPTION_RE.match(match.group("rest"))
        if not exception_match:
            raise RuntimeError(f"malformed exception event: {match.group(0)!r}")
        counts[exception_type_name(exception_match.group("name"))] += 1

    if not counts:
        raise RuntimeError(f"trace contains zero exception events for {TARGET_FUNC}")

    return {
        "exception_type_counts": [
            {"count": count, "exception_type": exception_type}
            for exception_type, count in sorted(counts.items())
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [
                {"count": "int", "exception_type": "str"},
            ]
        },
        "oracle_answer": compute_answer(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
