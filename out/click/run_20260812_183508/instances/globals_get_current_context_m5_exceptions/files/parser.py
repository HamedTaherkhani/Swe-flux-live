import argparse
import builtins
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/click/globals.py"
TARGET_FUNC = "click.globals.get_current_context"

QUESTION = (
    "Run the complete pytest class "
    "`click_qa/globals_get_current_context_m5_exceptions/files/testcase.py::"
    "TestGeneratedContextObservations`, including every method whose name "
    "starts with `test_`, and aggregate across ALL of those test methods. "
    "For every chronological invocation of `click.globals.get_current_context` "
    "in `src/click/globals.py`, count the exception observations made by that "
    "exact target frame and report totals grouped by exception type. An "
    "invocation means one `call` of the target function during this complete "
    "class run, numbered 1-based in chronological order; invocation numbers "
    "are not included in the output. An exception is observed once whenever "
    "Python raises it while executing code in that exact target frame or "
    "propagates it from a callee into that frame. Count the observation whether "
    "the target subsequently catches the exception, replaces it by raising "
    "another exception, or lets it propagate. An exception raised and fully "
    "handled inside a callee does not count because it never propagates into "
    "the target frame. If the same exception object is re-raised in the same "
    "target frame, each separate raise or propagation into the target frame is "
    "a new observation and counts again. Counts are totals over ALL invocations "
    "and ALL test methods, so the same type observed in five methods "
    "contributes five to its count. Test methods are identified by pytest ids "
    "of the form `repo/relative/test_file.py::ClassName::test_method_name` "
    "(for example, `checks/test_sample.py::TestSample::test_case`); method "
    "execution order does not affect these grouped totals. Exception type "
    "naming MUST use this convention: bare `type(exc).__name__` for built-in "
    "exceptions (e.g. `ValueError`, never `builtins.ValueError`), "
    "`module.QualName` for all others. For a non-built-in this means "
    "`type(exc).__module__ + \".\" + type(exc).__qualname__` (for example, "
    "`acme.errors.SignalError`). Return exactly one JSON object with shape "
    "`{\"exception_type_counts\": [{\"count\": <int>, "
    "\"exception_type\": <str>}, ...]}`. Each exception type observed at "
    "least once appears exactly once; `count` is a JSON integer and "
    "`exception_type` is a JSON string. Sort entries by the complete "
    "`exception_type` string ascending in Unicode code-point order. That "
    "complete string is the sole sort key; grouping makes it unique, so no "
    "further tie-break is possible. Do not deduplicate observations before "
    "counting, and do not include exception messages, invocation numbers, "
    "test ids, types with zero observations, or any additional keys."
)

TRACE_LINE = re.compile(
    r"(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_TYPE = re.compile(
    r"\bevent=exception exc=(?P<type>[A-Za-z_][A-Za-z0-9_]*):"
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path):
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    counts = Counter()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_LINE.search(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        if match.group("event") != "exception":
            continue

        exception_match = EXCEPTION_TYPE.search(raw_line)
        if exception_match is None:
            fail(f"cannot parse target exception event: {raw_line}")
        traced_name = exception_match.group("type")
        exception_class = getattr(builtins, traced_name, None)
        if (
            not isinstance(exception_class, type)
            or not issubclass(exception_class, BaseException)
        ):
            fail(
                "trace lacks the module-qualified identity required for "
                f"non-built-in exception type {traced_name!r}"
            )
        counts[exception_class.__name__] += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if not counts:
        fail(f"trace contains no exception events for {TARGET_FUNC}")

    return [
        {"count": counts[name], "exception_type": name}
        for name in sorted(counts)
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [
                {"count": "int", "exception_type": "str"}
            ]
        },
        "oracle_answer": {
            "exception_type_counts": parse_trace(args.trace_log)
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
