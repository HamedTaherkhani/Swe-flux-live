#!/usr/bin/env python3
import argparse
import builtins
from collections import Counter
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/utils/jinja2_chat_extension.py"
TARGET_FUNC = "haystack.utils.jinja2_chat_extension.ChatMessageExtension._validate_build_chat_message"
TARGET_FRAME_NAME = "haystack.utils.jinja2_chat_extension._validate_build_chat_message"

QUESTION = """Run all pytest test methods in
`haystack_qa/jinja2_chat_extension_validate_build_chat_message_m5_exceptions/files/testcase.py::TestGeneratedChatMessageValidation`
against this repository. The answer aggregates over ALL `test_*` methods in
that class. Pytest identifies each method as
`haystack_qa/jinja2_chat_extension_validate_build_chat_message_m5_exceptions/files/testcase.py::TestGeneratedChatMessageValidation::method_name`;
the methods are collected in pytest's normal name order, although that order
does not affect the requested totals.

Across that whole run, count exception observations in the exact function
`haystack.utils.jinja2_chat_extension.ChatMessageExtension._validate_build_chat_message`
in `haystack/utils/jinja2_chat_extension.py`. An invocation is one entry into
that exact function frame (one Python function-call event), numbered from 1 in
chronological order across the complete run.

An exception is observed in the target frame each time either code executing
in that exact frame raises it or an exception propagates into that frame from
a callee. Count it once per target-frame observation. An exception raised and
fully handled inside a callee does not count because it never propagates into
the target frame. If the same exception object is re-raised in the target
frame, each re-raise is a new target-frame observation and counts again.
Handling or re-raising that object only inside a callee does not add another
target-frame count; only its eventual propagation into the target counts.
Likewise, catches performed later by callers or by the test do not add counts.

Return exactly one JSON object with the single key
`exception_type_counts`. Its value is a JSON list containing one object for
every observed exception type; every object has exactly the keys `count`
(a JSON integer) and `exception_type` (a JSON string). Counts are totals over
ALL invocations and ALL test methods, so the same type raised in five methods
contributes five. Aggregate duplicate observations of a type into one row;
do not deduplicate observations before counting.

For exception type names, use bare `type(exc).__name__` for built-in
exceptions (e.g. `ValueError`, never `builtins.ValueError`), and
`module.QualName` for all others. If an exception message is inspected while
computing an observation, message means exact `str(exc)`, with no `repr`
quotes, truncation, or whitespace normalization; messages are not emitted in
this answer shape. Sort the list by `exception_type` ascending using Unicode
code-point order. Since aggregation emits exactly one row per type, equal
primary sort keys cannot occur and there is no secondary tie-breaker."""

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r" event=exception exc=(?P<type>[^: ]+): .*? locals=")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def normalized_exception_name(raw_name: str) -> str:
    candidate = getattr(builtins, raw_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__
    fail(
        "trace records only a bare name for non-built-in exception "
        f"{raw_name!r}, so module-qualified naming is impossible"
    )


def parse_counts(trace_path: Path) -> dict[str, list[dict[str, object]]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    counts: Counter[str] = Counter()
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        event_match = EVENT_RE.match(raw_line)
        if event_match is None:
            continue
        path = event_match.group("path").replace("\\", "/")
        if not path.endswith(f"/{TARGET_FILE}"):
            continue
        if event_match.group("func") != TARGET_FRAME_NAME:
            continue

        target_events += 1
        if event_match.group("event") != "exception":
            continue
        exception_match = EXCEPTION_RE.search(raw_line)
        if exception_match is None:
            fail(f"malformed target exception event: {raw_line!r}")
        exception_name = normalized_exception_name(exception_match.group("type"))
        counts[exception_name] += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if not counts:
        fail(f"trace contains no exception observations for {TARGET_FUNC}")

    rows = [
        {"count": counts[exception_type], "exception_type": exception_type}
        for exception_type in sorted(counts)
    ]
    return {"exception_type_counts": rows}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [
                {"count": "int", "exception_type": "str"},
            ]
        },
        "oracle_answer": parse_counts(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(oracle, indent=2, sort_keys=True) + "\n"
    args.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
