#!/usr/bin/env python3
import argparse
import builtins
from collections import Counter
import json
import re
import sys
from pathlib import Path

import lark.exceptions


TARGET_FILE = "lark/visitors.py"
TARGET_FUNC = "lark.visitors.Transformer._call_userfunc"
TEST_FILE = "lark_qa/visitors_call_userfunc_m5_exceptions/files/testcase.py"
TEST_CLASS = "TestTransformerExceptionAggregation"


def fail(message):
    raise RuntimeError(message)


def canonical_exception_name(short_name):
    builtin_type = getattr(builtins, short_name, None)
    if (
        isinstance(builtin_type, type)
        and issubclass(builtin_type, BaseException)
    ):
        return builtin_type.__name__

    lark_type = getattr(lark.exceptions, short_name, None)
    if (
        isinstance(lark_type, type)
        and issubclass(lark_type, BaseException)
    ):
        return "%s.%s" % (lark_type.__module__, lark_type.__qualname__)

    fail("cannot canonicalize traced exception type: %s" % short_name)


def parse_trace(trace_path):
    if not trace_path.is_file():
        fail("trace log is missing: %s" % trace_path)
    if trace_path.stat().st_size == 0:
        fail("trace log is empty: %s" % trace_path)

    event_re = re.compile(
        r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
        r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
        r"(?:\s+exc=(?P<exception_type>[A-Za-z_][A-Za-z0-9_]*):)?"
    )
    target_events = []
    exception_counts = Counter()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_re.search(raw_line)
        if not match:
            continue
        filename = match.group("file").replace("\\", "/")
        if not filename.endswith("/" + TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        event = match.group("event")
        target_events.append(event)
        if event == "exception":
            short_name = match.group("exception_type")
            if not short_name:
                fail("target exception event has no parseable type: %s" % raw_line)
            exception_counts[canonical_exception_name(short_name)] += 1

    if not target_events:
        fail("trace contains zero events for %s" % TARGET_FUNC)
    if "call" not in target_events:
        fail("trace contains no call event for %s" % TARGET_FUNC)
    if not exception_counts:
        fail("trace contains no exception events for %s" % TARGET_FUNC)

    return {
        "exception_type_counts": [
            {"count": count, "exception_type": exception_type}
            for exception_type, count in sorted(exception_counts.items())
        ]
    }


def build_question():
    return (
        "Run every pytest test method whose name begins with `test_` in class "
        f"`{TEST_CLASS}` from `{TEST_FILE}` (equivalently, run the pytest id "
        f"`{TEST_FILE}::{TEST_CLASS}`), and aggregate over ALL test methods in "
        "that class. During that complete run, consider every invocation of "
        f"`{TARGET_FUNC}` in `{TARGET_FILE}`. An invocation means one `call` of "
        "that function during the run and invocations are 1-based in chronological "
        "order, although invocation numbers are not included in the answer. Count an "
        "exception observation whenever Python execution in that exact target frame "
        "reports an exception event: this includes an exception raised directly by "
        "code in the frame and an exception propagated into it from a callee. Count "
        "one for each target-frame observation across every invocation. An exception "
        "raised and fully handled inside a callee, without propagating into the target "
        "frame, does not count. If the same exception object is re-raised in the target "
        "frame and is consequently observed there a second time, count that re-raise "
        "again. Likewise, when one observed exception is handled and a new wrapper "
        "exception is raised, count both observations under their respective types. "
        "Exception type naming MUST use the same convention as S5: bare "
        "`type(exc).__name__` for built-ins (e.g. `ValueError`, never "
        "`builtins.ValueError`), `module.QualName` for all others. Message = exact "
        "`str(exc)`. Messages are not fields in this answer. Counts are totals over "
        "ALL invocations and ALL test methods, so repeated observations of the same "
        "type in five methods contribute five to that type's count; do not deduplicate "
        "events. Aggregate entries having the same canonical exception-type string. "
        "Return exactly one JSON object with the sole key `exception_type_counts`; its "
        "value is a JSON list of objects, each having exactly `count` (a JSON integer) "
        "and `exception_type` (a JSON string). Sort that list by `exception_type` in "
        "ascending Unicode code-point order. Because equal type strings are aggregated "
        "into one entry, no ordering tie remains and no secondary tie-break is applied. "
        "Use no additional keys and include every type observed at least once."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = parse_trace(Path(args.trace_log))
    payload = {
        "question_kind": "M5_Exceptions",
        "question": build_question(),
        "template_answer": {
            "exception_type_counts": [
                {"count": "int", "exception_type": "str"}
            ]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise
