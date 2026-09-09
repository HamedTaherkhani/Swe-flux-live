#!/usr/bin/env python3
import argparse
import builtins
import json
import pathlib
import re
import sys


TARGET_FILE = "src/instructlab/model/dk_bench_utils.py"
TARGET_FUNC = "instructlab.model.dk_bench_utils.run_dk_bench"
EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) "
    + re.escape(TARGET_FUNC)
    + r" event=(?P<event>call|line|return|exception)(?: |$)"
)
EXCEPTION_RE = re.compile(r" event=exception exc=(?P<name>[^:\s]+): ")

QUESTION = """Run only the pytest test
`instruct_lab_qa/dk_bench_utils_run_dk_bench_m5_exceptions/files/testcase.py::TestDkBenchExceptionEvents::test_layered_outcomes_across_generated_cases`
and consider every invocation of
`instructlab.model.dk_bench_utils.run_dk_bench` in
`src/instructlab/model/dk_bench_utils.py`. An invocation means one call of that
function during this selected test, numbered 1-based in chronological call
order.

What distinct exception types are observed in the target function's frame
over the whole selected test run? An exception is observed each time Python's
line-tracing semantics produce an `exception` event in that frame: count an
exception raised directly by the target, an exception propagating into the
target from a callee at the target's call site, and a re-raise as separate
events, whether the exception is subsequently caught in the target or escapes
the invocation. Ignore exception events in every other function's frame.

Return exactly one JSON object with the canonical shape
`{"exception_types": ["str"]}`. Format each built-in exception using bare
`type(exc).__name__` (for example, `ValueError`, never
`builtins.ValueError`). Format every non-built-in exception as
`type(exc).__module__ + "." + type(exc).__qualname__` (for example,
`package.WidgetError`). Normalize every observed event this way, remove
duplicates by the resulting string, then sort the strings in ascending Python
lexicographic (Unicode code-point) order. The array contains those sorted
strings; it is not chronological. Do not report exception messages, event
counts, invocation numbers, or JSON null placeholders."""


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_trace(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    exception_names = []
    for line in text.splitlines():
        match = EVENT_RE.search(line)
        if not match:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue
        target_events.append(match.group("event"))
        if match.group("event") == "exception":
            exception_match = EXCEPTION_RE.search(line)
            if exception_match is None:
                fail(f"could not parse target exception event: {line}")
            exception_names.append(exception_match.group("name"))

    if not target_events:
        fail(
            "trace contains zero events for "
            f"{TARGET_FUNC} in {TARGET_FILE}"
        )
    if not exception_names:
        fail("target trace contains zero exception events")

    builtin_names = {
        name
        for name, value in vars(builtins).items()
        if isinstance(value, type) and issubclass(value, BaseException)
    }
    unknown = sorted(set(exception_names) - builtin_names)
    if unknown:
        fail(
            "trace records a non-built-in exception without enough module "
            f"metadata to format it unambiguously: {unknown}"
        )
    return sorted(set(exception_names))


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = {"exception_types": parse_trace(pathlib.Path(args.trace_log))}
    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": answer,
    }

    output_path = pathlib.Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
