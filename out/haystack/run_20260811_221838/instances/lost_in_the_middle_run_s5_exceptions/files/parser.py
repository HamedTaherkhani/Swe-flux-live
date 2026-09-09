#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/components/rankers/lost_in_the_middle.py"
TARGET_FUNC = "haystack.components.rankers.lost_in_the_middle.LostInTheMiddleRanker.run"
TARGET_FRAME = "haystack.components.rankers.lost_in_the_middle.run"
EXCEPTION_LINE = 124

QUESTION = """Run only the pytest test
`haystack_qa/lost_in_the_middle_run_s5_exceptions/files/testcase.py::TestLostInTheMiddleRuntimeFailure::test_generated_documents_with_late_missing_payload`
against this repository. During that test's sole invocation of the exact
function `haystack.components.rankers.lost_in_the_middle.LostInTheMiddleRanker.run`
in `haystack/components/rankers/lost_in_the_middle.py`, what are the type and
message of the single exception first observed in that function's frame while
it evaluates the statement/expression beginning at line 124 and then propagated
uncaught out of that frame to its caller?

Return exactly one JSON object with exactly these two string keys:
`exception_message` and `exception_type`. `exception_message` is the exact
`str(exc)`, character for character, with no surrounding `repr` quotes,
truncation, or whitespace normalization; use JSON escaping only as required to
encode that string. For `exception_type`, use bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`).

An invocation means one entry into that exact target function frame (one Python
function call), numbered from 1 in chronological order; this test makes exactly
one such invocation. Count only the exception observation in that target frame
at the specified line which subsequently exits that frame. Ignore any
observation made later when the caller or test catches the same exception, and
ignore exceptions wholly handled in other frames. There is exactly one
qualifying exception, so no sorting or deduplication is performed.

Line 124 means the absolute, 1-based line number in the named repository file
as it exists for this run. For a multi-line statement or expression, its line
is where that statement or expression begins. Decorator, `def`, and docstring
lines are not eligible exception locations for this question."""

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(r" event=exception exc=(?P<exc>.*?) locals=")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def exception_from_repr(type_name: str, value_repr: str) -> BaseException:
    try:
        expression = ast.parse(value_repr, mode="eval").body
    except SyntaxError as exc:
        fail(f"cannot parse exception representation {value_repr!r}: {exc}")

    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
        fail(f"unexpected exception representation: {value_repr!r}")
    if expression.func.id != type_name or expression.keywords:
        fail(f"exception representation does not match type {type_name!r}: {value_repr!r}")

    exception_class = getattr(builtins, type_name, None)
    if not isinstance(exception_class, type) or not issubclass(exception_class, BaseException):
        fail(f"trace does not provide a module for non-built-in exception {type_name!r}")

    try:
        args = [ast.literal_eval(argument) for argument in expression.args]
        return exception_class(*args)
    except (TypeError, ValueError, SyntaxError) as exc:
        fail(f"cannot reconstruct exception from {value_repr!r}: {exc}")


def parse_exception(trace_path: Path) -> dict[str, str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_event_count = 0
    target_call_count = 0
    qualifying: list[tuple[str, str]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_path = match.group("path").replace("\\", "/")
        if not normalized_path.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FRAME:
            continue

        target_event_count += 1
        if match.group("event") == "call":
            target_call_count += 1
        if match.group("event") != "exception":
            continue
        if int(match.group("line")) != EXCEPTION_LINE:
            continue

        payload_match = EXCEPTION_RE.search(raw_line)
        if payload_match is None:
            fail("qualifying target exception event has no exception payload")
        exception_field = payload_match.group("exc")
        type_name, separator, value_repr = exception_field.partition(": ")
        if not separator or not type_name or not value_repr:
            fail(f"malformed target exception payload: {exception_field!r}")
        qualifying.append((type_name, value_repr))

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if target_call_count != 1:
        fail(f"expected exactly one target invocation, found {target_call_count}")
    if len(qualifying) != 1:
        fail(
            f"expected exactly one target exception event at line {EXCEPTION_LINE}, "
            f"found {len(qualifying)}"
        )

    type_name, value_repr = qualifying[0]
    exception = exception_from_repr(type_name, value_repr)
    return {
        "exception_message": str(exception),
        "exception_type": type(exception).__name__,
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": parse_exception(args.trace_log),
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
