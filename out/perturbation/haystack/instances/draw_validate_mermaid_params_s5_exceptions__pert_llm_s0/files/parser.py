#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/core/pipeline/draw.py"
TARGET_FUNC = "haystack.core.pipeline.draw._validate_mermaid_params"

QUESTION = """Run only the pytest test
`haystack_qa/draw_validate_mermaid_params_s5_exceptions/files/testcase.py::TestMermaidParameterValidation::test_generated_render_parameter_matrix`
against this repository. Across all invocations during that test, consider only
the exact function `haystack.core.pipeline.draw._validate_mermaid_params` whose
code is in `haystack/core/pipeline/draw.py`. What are the type and message of
the sole exception raised by a `raise` statement in that target function and
propagated out of its frame to its immediate caller?

Return exactly one JSON object with exactly these two string keys:
`exception_message` and `exception_type`. `exception_message` is the exact
`str(exc)`, character for character, with no surrounding representation quotes,
escaping beyond that required by JSON, truncation, or whitespace normalization.
For `exception_type`, use bare `type(exc).__name__` for built-in exceptions
(e.g. `ValueError` — never `builtins.ValueError`), and `module.QualName` for all
others (e.g. `haystack.core.errors.PipelineError`).

An invocation is one entry into that exact target function frame, corresponding
to one Python `call` event; invocations are considered in chronological,
1-based call order. Count an exception only when execution of a `raise`
statement in the target frame creates the exception and the target does not
catch it, so it exits that frame into `_to_mermaid_image`. Ignore exceptions
created in callees or any other frame, and ignore the test's later catch of the
propagated exception. There is exactly one qualifying exception in this test,
so no sorting or deduplication is performed."""

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
    qualifying = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_path = match.group("path").replace("\\", "/")
        if not normalized_path.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_event_count += 1
        if match.group("event") != "exception":
            continue
        payload_match = EXCEPTION_RE.search(raw_line)
        if payload_match is None:
            fail("target exception event has no exception payload")
        exception_field = payload_match.group("exc")
        type_name, separator, value_repr = exception_field.partition(": ")
        if not separator or not type_name or not value_repr:
            fail(f"malformed target exception payload: {exception_field!r}")
        qualifying.append((type_name, value_repr))

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if len(qualifying) != 1:
        fail(f"expected exactly one target exception event, found {len(qualifying)}")

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
