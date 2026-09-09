#!/usr/bin/env python3
import argparse
import builtins
import importlib
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "haystack/utils/type_serialization.py"
TARGET_FUNC = "haystack.utils.type_serialization.deserialize_type"

QUESTION = """Run all twelve `test_*` methods in `TestDeserializeTypeExceptions` from `haystack_qa/type_serialization_deserialize_type_m5_exceptions/files/testcase.py`: `test_01_generated_builtin_successes`, `test_02_nested_generic_successes`, `test_03_generated_unknown_bare_names`, `test_04_generated_missing_modules`, `test_05_existing_modules_missing_attributes`, `test_06_invalid_generic_main_types`, `test_07_invalid_nested_generic_arguments`, `test_08_unsubscriptable_builtin_mains`, `test_09_attribute_driven_generic_failures`, `test_10_arithmetic_and_reraised_lookup_failures`, `test_11_decode_bounds_and_generator_failures`, and `test_12_mixed_safe_swallowed_and_failing_paths`. The answer aggregates the complete run of every listed method. Each pytest id is the named file path followed by `::TestDeserializeTypeExceptions::` and the method name, for example `haystack_qa/type_serialization_deserialize_type_m5_exceptions/files/testcase.py::TestDeserializeTypeExceptions::test_02_nested_generic_successes`; pytest determines method execution order, but that order does not affect the requested totals.

Across that complete run, consider every invocation of the exact function `haystack.utils.type_serialization.deserialize_type` in `haystack/utils/type_serialization.py`, including calls made directly by the tests, calls made by their shared helper, and recursive calls made by the target itself. An invocation means one `call` of that exact function; invocations are 1-based in chronological order across all methods, although invocation numbers are not emitted.

An exception is observed when Python produces an exception event in that exact target-function frame. This includes an exception raised by an operation executing in the frame and an exception propagated into the frame from a callee. Count each target-frame exception event once. An exception raised and fully handled inside a callee does not count because it never produces an exception event in the target frame. If the same exception object is re-raised and produces another exception event in the same target frame, count that later event again. Likewise, when a handler observes one exception and raises a different wrapper exception, count both if both produce events in the target frame. Events in comprehension frames, helper frames, and all other functions are excluded, even when their qualified names begin with the target function's name. Normal calls, executed lines, and returns do not count.

Exception type naming uses bare `type(exc).__name__` for built-ins (e.g. `ValueError`, never `builtins.ValueError`), `module.QualName` for all others. Message = exact `str(exc)`. Messages are not included in this answer shape. Built-in status is determined by the exception class's `__module__ == "builtins"`; for every other class, concatenate `__module__`, a dot, and `__qualname__`.

Aggregate observations by that exact normalized exception-type string over all invocations and all test methods. Counts are totals, not counts of distinct invocations or methods: the same type observed in five methods contributes five observations, and repeated observations in one invocation each contribute separately. Emit exactly `{"exception_type_counts": [{"count": <int>, "exception_type": <str>}, ...]}` as JSON. There is exactly one object per observed normalized type, with no unobserved types and no duplicate type objects after aggregation. Sort objects by `exception_type` ascending in lexicographic Unicode code-point order. Since aggregation makes each exception-type string unique, equal primary keys cannot occur and no secondary tie-breaker is needed. `count` is a JSON integer and `exception_type` is a JSON string; no `null`, empty-string, `repr()`, or message substitution is used."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)(?: |$)"
)
EXCEPTION_RE = re.compile(r" event=exception exc=(?P<type>[^:\s]+): ")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def normalize_exception_type(type_name):
    builtin_type = getattr(builtins, type_name, None)
    if isinstance(builtin_type, type) and issubclass(builtin_type, BaseException):
        return builtin_type.__name__

    target_module = importlib.import_module("haystack.utils.type_serialization")
    imported_type = getattr(target_module, type_name, None)
    if isinstance(imported_type, type) and issubclass(imported_type, BaseException):
        return f"{imported_type.__module__}.{imported_type.__qualname__}"

    raise ValueError(
        f"cannot resolve non-built-in exception type {type_name!r} "
        f"from builtins or the target module"
    )


def harvest(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    counts = Counter()

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if (
                not match
                or match.group("func") != TARGET_FUNC
                or TARGET_FILE not in match.group("file").replace("\\", "/")
            ):
                continue

            target_events += 1
            if match.group("event") == "call":
                target_calls += 1
            if match.group("event") != "exception":
                continue

            exception_match = EXCEPTION_RE.search(raw_line)
            if exception_match is None:
                raise ValueError(f"target exception event has no parseable exception type: {raw_line.rstrip()}")
            counts[normalize_exception_type(exception_match.group("type"))] += 1

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    if not counts:
        raise ValueError(f"trace contains no exception event for {TARGET_FUNC}")

    return [
        {"count": counts[exception_type], "exception_type": exception_type}
        for exception_type in sorted(counts)
    ]


def main():
    args = parse_args()
    output_path = Path(args.out)
    exception_type_counts = harvest(Path(args.trace_log))
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_type_counts": [{"count": "int", "exception_type": "str"}]
        },
        "oracle_answer": {"exception_type_counts": exception_type_counts},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {output_path} with {len(exception_type_counts)} observed exception types"
    )


if __name__ == "__main__":
    main()
