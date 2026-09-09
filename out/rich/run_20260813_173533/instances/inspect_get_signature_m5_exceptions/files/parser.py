#!/usr/bin/env python3
"""Parse trace log into M5_Exceptions oracle for Inspect._get_signature."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

QUESTION_KIND = "M5_Exceptions"
TARGET_FILE = "rich/_inspect.py"
TARGET_FUNC = "rich._inspect.Inspect._get_signature"
TEST_FILE = "rich_qa/inspect_get_signature_m5_exceptions/files/testcase.py"
TEST_CLASS = "InspectGetSignatureExceptionsTest"

QUESTION = f"""\
During the pytest run of every test method in class {TEST_CLASS} defined in \
{TEST_FILE} (pytest ids look like \
{TEST_FILE}::{TEST_CLASS}::test_pure_python_methods_only), consider the function \
{TARGET_FUNC} defined in {TARGET_FILE} (the def statement begins on line 82).

The answer aggregates exception observations across the entire pytest session: \
all invocations of {TARGET_FUNC} from every test method listed above, in pytest \
collection order.

Observation rule: count each sys.settrace event=exception whose func field equals \
exactly {TARGET_FUNC} (module-qualified format: package.module.Class.method, for \
example rich.console.Console.print). An observation is recorded when an exception \
propagates into the {TARGET_FUNC} frame from a direct callee (such as inspect.signature \
or inspect.getfile) before any except handler in {TARGET_FUNC} runs. Exceptions raised \
and fully handled inside a callee without entering the {TARGET_FUNC} frame do not \
count. Exceptions raised in {TARGET_FUNC} itself and not caught inside that frame \
would count, though this scenario does not arise in the assigned tests. A re-raise of \
the same exception object in the same frame counts again; the assigned tests do not \
re-raise inside {TARGET_FUNC}.

Exception type naming: use bare type(exc).__name__ for built-in exceptions (for \
example ValueError, never builtins.ValueError) and module.QualName for all other \
exception classes (for example json.decoder.JSONDecodeError). The parser and solver \
must apply this rule identically.

Counting: totals over all invocations and all test methods — if ValueError is observed \
five times across the session, its count is 5.

Report JSON with top-level key exception_type_counts whose value is a list of objects, \
each with exactly these keys:
- exception_type (str): the type name per the naming rule above
- count (int): total observations of that type in the target frame

Sort the list by exception_type ascending (Unicode code-point order). No tie-break \
beyond the type string is needed.

Only exception events in {TARGET_FUNC} count; ignore line, call, and return events for \
this question.\
"""

TEMPLATE_ANSWER = {
    "exception_type_counts": [
        {"count": "int", "exception_type": "str"},
    ],
}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

EXC_FIELD_RE = re.compile(r" exc=([A-Za-z_][\w.]*?):")


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    marker = TARGET_FILE
    idx = normalized.rfind(marker)
    if idx == -1:
        raise ValueError(f"trace path does not contain {marker!r}: {path!r}")
    return normalized[idx:]


def _format_exception_type(raw_line: str) -> str:
    match = EXC_FIELD_RE.search(raw_line)
    if not match:
        raise ValueError(f"unable to parse exception type from trace line: {raw_line!r}")
    return match.group(1)


def _parse_exception_counts(trace_log: Path) -> Counter[str]:
    if not trace_log.is_file():
        raise SystemExit(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"trace log is empty: {trace_log}")

    counts: Counter[str] = Counter()
    matched_events = 0
    exception_events = 0

    for raw_line in text.splitlines():
        match = TRACE_LINE_RE.match(raw_line)
        if not match:
            continue

        file_path = _normalize_file(match.group("file"))
        if file_path != TARGET_FILE:
            continue

        func_name = match.group("func")
        if func_name != TARGET_FUNC:
            continue

        matched_events += 1
        event = match.group("event")
        if event != "exception":
            continue

        exception_events += 1
        exc_type = _format_exception_type(raw_line)
        counts[exc_type] += 1

    if matched_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if exception_events == 0:
        raise SystemExit(
            f"trace log contains zero exception events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    return counts


def _build_answer(counts: Counter[str]) -> dict:
    if not counts:
        raise SystemExit("no exception types observed in target frame")

    exception_type_counts = [
        {"exception_type": exc_type, "count": counts[exc_type]}
        for exc_type in sorted(counts)
    ]
    return {"exception_type_counts": exception_type_counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    counts = _parse_exception_counts(args.trace_log)
    oracle_answer = _build_answer(counts)

    payload = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
