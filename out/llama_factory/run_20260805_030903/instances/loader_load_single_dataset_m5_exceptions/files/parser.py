#!/usr/bin/env python3
import argparse
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/data/loader.py"
TARGET_FUNC = "llamafactory.data.loader._load_single_dataset"

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/loader_load_single_dataset_m5_exceptions/files/testcase.py::"
    "TestLayeredDatasetExceptions::test_seeded_dataset_loading_matrix`. Across the complete run, "
    "inspect every invocation of `llamafactory.data.loader._load_single_dataset` in "
    "`src/llamafactory/data/loader.py`. An invocation is one runtime entry into that exact "
    "function, and invocations are numbered 1-based in chronological entry order. For all such "
    "invocations, collect the runtime class of every exception that is raised while evaluating a "
    "statement in the target frame or propagates from an operation called by the target into that "
    "frame. Include an exception even if the target subsequently catches it, and include an "
    "exception that causes the target frame to exit. Exclude exceptions raised and fully handled "
    "inside another frame without propagating into the target frame, and exclude all exception "
    "activity before entry to or after exit from the target frame. Exception type naming MUST use "
    "this convention: bare `type(exc).__name__` for built-ins (e.g. `OSError`, never "
    "`builtins.OSError`), `module.QualName` for all others "
    "(e.g. `acme.errors.ParseFailure`). Remove duplicate type names across the whole run, then sort "
    "the remaining strings in ascending lexicographic order by their exact emitted Unicode code "
    "points; there is no chronological tie-breaker because duplicates have already been removed. "
    "Return exactly one JSON object with exactly one key, `exception_types`, whose value is a JSON "
    "array of those strings in that order. Do not report exception messages, counts, invocation "
    "numbers, line numbers, or `repr` values; no empty-string, JSON-null, or omitted-value "
    "substitution applies."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/data/loader\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b(?P<rest>.*)"
)
EXCEPTION_RE = re.compile(r" exc=(?P<type>[^:\s]+): .* locals=")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def normalize_type_name(trace_type_name):
    candidate = getattr(builtins, trace_type_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__
    if "." in trace_type_name:
        return trace_type_name
    fail(
        "trace does not contain the module-qualified name required for non-built-in "
        f"exception type {trace_type_name!r}"
    )


def read_target_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((match.group("event"), match.group("rest")))
    return events


def extract_exception_types(events):
    call_count = sum(event == "call" for event, _rest in events)
    if call_count == 0:
        fail(f"trace contains no call events for {TARGET_FUNC}")

    observed = []
    for event, rest in events:
        if event != "exception":
            continue
        match = EXCEPTION_RE.search(rest)
        if not match:
            fail(f"cannot parse target exception event: {rest!r}")
        observed.append(normalize_type_name(match.group("type")))

    if not observed:
        fail(f"trace contains no exception events for {TARGET_FUNC}")
    return sorted(set(observed))


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = read_target_events(trace_path)
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    payload = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_types": ["str"]},
        "oracle_answer": {"exception_types": extract_exception_types(events)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
