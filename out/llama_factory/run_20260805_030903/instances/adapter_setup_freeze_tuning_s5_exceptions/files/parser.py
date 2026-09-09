#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/model/adapter.py"
TARGET_FUNC = "llamafactory.model.adapter._setup_freeze_tuning"

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/adapter_setup_freeze_tuning_s5_exceptions/files/testcase.py::"
    "TestFreezeTuningExceptionPropagation::test_seeded_parameter_scan_failure`. During that run, "
    "consider the sole invocation of `llamafactory.model.adapter._setup_freeze_tuning` in "
    "`src/llamafactory/model/adapter.py`. Report the exception that is raised into that target "
    "frame while it advances the first `for name, _ in model.named_parameters()` loop and then "
    "propagates out of the target to its direct caller, `llamafactory.model.adapter.init_adapter`. "
    "An invocation is one runtime entry into that exact target function during the complete test "
    "run; invocations would be numbered 1-based in chronological entry order, and this test makes "
    "exactly one. Here, \"propagates out\" means that the target frame exits because of the same "
    "exception object and does not catch or suppress it before it reaches the named direct caller. "
    "Report the exception message as exact `str(exc)`, character for character; an absent textual "
    "message is the JSON string `\"\"`, never JSON null and never an omitted key. Exception type "
    "naming MUST use this convention: bare `type(exc).__name__` for built-in exceptions (e.g. "
    "`ValueError` — never `builtins.ValueError`), and `module.QualName` for all others (e.g. "
    "`haystack.core.errors.PipelineError`). Return exactly one JSON object with exactly two JSON "
    "string fields: `exception_message` and `exception_type`. Show object keys in ascending "
    "lexicographic order (`exception_message` before `exception_type`). Do not truncate or "
    "otherwise normalize either string; no sorting or deduplication of exception events applies "
    "because exactly the one propagating exception from the sole target invocation is reported."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/model/adapter\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b(?P<rest>.*)"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def exception_message_from_repr(type_name, value_repr):
    try:
        expression = ast.parse(value_repr, mode="eval").body
    except SyntaxError as exc:
        fail(f"cannot parse exception repr {value_repr!r}: {exc}")

    if not isinstance(expression, ast.Call) or expression.keywords:
        fail(f"exception repr is not a positional constructor call: {value_repr!r}")

    if isinstance(expression.func, ast.Name):
        constructor_name = expression.func.id
    elif isinstance(expression.func, ast.Attribute):
        constructor_name = expression.func.attr
    else:
        fail(f"cannot identify exception constructor in {value_repr!r}")

    if constructor_name != type_name.rsplit(".", 1)[-1]:
        fail(f"exception constructor {constructor_name!r} does not match type {type_name!r}")

    try:
        arguments = [ast.literal_eval(argument) for argument in expression.args]
    except (ValueError, SyntaxError) as exc:
        fail(f"exception repr has non-literal arguments: {value_repr!r}: {exc}")

    if not arguments:
        return ""
    if len(arguments) == 1:
        return str(arguments[0])
    return str(tuple(arguments))


def normalize_type_name(trace_type_name):
    candidate = getattr(builtins, trace_type_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__
    if "." in trace_type_name:
        return trace_type_name
    fail(f"non-built-in exception type is not module-qualified: {trace_type_name!r}")


def read_target_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((match.group("event"), match.group("rest")))
    return events


def extract_answer(events):
    call_count = sum(event == "call" for event, _ in events)
    if call_count != 1:
        fail(f"expected exactly one target invocation, found {call_count}")

    exceptions = []
    closed = False
    for event, rest in events:
        if event == "exception":
            match = re.search(r" exc=(?P<type>[^:\s]+): (?P<repr>.*) locals=", rest)
            if not match:
                fail(f"cannot parse target exception event: {rest!r}")
            exceptions.append((match.group("type"), match.group("repr")))
        elif event == "return":
            closed = True

    if len(exceptions) != 1:
        fail(f"expected exactly one target exception event, found {len(exceptions)}")
    if not closed:
        fail("target invocation has no frame-closing return event")

    trace_type, value_repr = exceptions[0]
    return {
        "exception_message": exception_message_from_repr(trace_type, value_repr),
        "exception_type": normalize_type_name(trace_type),
    }


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
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": extract_answer(events),
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
