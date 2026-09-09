import argparse
import builtins
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/click/core.py"
TARGET_FUNC = "click.core.Parameter.handle_parse_result"
PROCESS_VALUE_LINE = 2778

QUESTION = (
    "Run only the pytest test "
    "`click_qa/core_handle_parse_result_s5_exceptions/files/testcase.py::"
    "TestGeneratedResilientParsing::"
    "test_generated_callback_failures_are_absorbed`. Across all chronological "
    "invocations of `click.core.Parameter.handle_parse_result` in "
    "`src/click/core.py` caused by that test, what set of exception types is "
    "caught by that function's `except Exception` suite? An invocation means "
    "one call of the target function, counted 1-based in chronological order. "
    "For this question, an exception is caught only when it is raised while "
    "evaluating `self.process_value(ctx, value)` on line 2778, reaches the "
    "target function's frame at that line, and execution then enters the "
    "`except Exception` suite at lines 2779-2785 instead of propagating out of "
    "that invocation. Source line numbers are absolute, 1-based line numbers "
    "in the named repository file; for a multi-line statement or expression, "
    "the executed line is the line where that statement or expression begins. "
    "Report each distinct caught exception type once, even if it is caught in "
    "multiple invocations. Exception type naming MUST use this convention: "
    "bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` — "
    "never `builtins.ValueError`), and `module.QualName` for all others (e.g. "
    "`acme.errors.SignalError`), where the latter is "
    "`type(exc).__module__ + \".\" + type(exc).__qualname__`. Sort the "
    "deduplicated strings in ascending lexicographic order by Unicode code "
    "point, with the complete type-name string as the sole sort key. Return "
    "exactly one JSON object with shape "
    "`{\"caught_exception_kinds\": [<str>, ...]}`; the list elements are JSON "
    "strings, and no exception messages or additional keys are included."
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
    caught_names = set()

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
        if (
            match.group("event") != "exception"
            or int(match.group("line")) != PROCESS_VALUE_LINE
        ):
            continue

        exception_match = EXCEPTION_TYPE.search(raw_line)
        if exception_match is None:
            fail(f"cannot parse target exception event: {raw_line}")

        name = exception_match.group("type")
        exception_class = getattr(builtins, name, None)
        if (
            not isinstance(exception_class, type)
            or not issubclass(exception_class, Exception)
        ):
            fail(
                "target exception is not a built-in Exception subclass; "
                f"trace does not contain its module-qualified name: {name}"
            )
        caught_names.add(exception_class.__name__)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if not caught_names:
        fail(
            f"trace contains no caught exception events at "
            f"{TARGET_FILE}:{PROCESS_VALUE_LINE}"
        )

    return sorted(caught_names)


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {
            "caught_exception_kinds": parse_trace(args.trace_log)
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
