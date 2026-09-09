#!/usr/bin/env python3
import argparse
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/chat/chat_model.py"
TARGET_FUNC = "llamafactory.chat.chat_model.run_chat"

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/chat_model_run_chat_m5_exceptions/files/testcase.py::"
    "TestChatCliLayeredExceptions::test_seeded_cli_invocations`. Pytest ids in this question use "
    "the exact `repo-relative/path.py::ClassName::method_name` format (for example, "
    "`tests/test_widget.py::TestWidget::test_case`). Across that complete test run, inspect every "
    "invocation of `llamafactory.chat.chat_model.run_chat` in "
    "`src/llamafactory/chat/chat_model.py`. An invocation is one runtime `call` entry into that "
    "exact function and invocations are numbered 1-based in chronological entry order. Collect "
    "the runtime class of every Python exception event delivered to a target invocation's own "
    "frame: include an exception raised while evaluating an operation in that frame, an exception "
    "propagating into it from a function, callable, or iterator operation it invokes, an exception "
    "the target catches and continues from, an exception used internally by Python iteration "
    "control, and an exception that exits the target frame. Exclude exceptions raised and fully "
    "handled in another frame without propagating into the target frame, and exclude activity "
    "before target entry or after target exit. Generator resumptions are not separate target "
    "invocations; they matter only when their exception propagates to the target frame. Exception "
    "type naming MUST use the same convention as S5, stated verbatim in the question: bare "
    "`type(exc).__name__` for built-ins (e.g. `ValueError`, never `builtins.ValueError`), "
    "`module.QualName` for all others. Remove duplicate emitted type-name strings across all "
    "invocations, then sort the remaining strings in ascending lexicographic order by exact "
    "Unicode code-point order. Deduplication happens before sorting, so there is no chronological "
    "tie-breaker. Return exactly one JSON object with exactly one key, `exception_types`; its value "
    "is a JSON array of those strings in that order. Report neither messages nor counts, "
    "invocation numbers, line numbers, or values, so no `repr` versus `str`, empty-string, JSON "
    "`null`, or omitted-value convention applies."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/chat/chat_model\.py):(?P<line>\d+) "
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
        "trace lacks the module-qualified name required for non-built-in "
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
    if not any(event == "call" for event, _rest in events):
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
