from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/context/context.py"
TARGET_FUNC = "kedro.framework.context.context._convert_paths_to_absolute_posix"
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?P<details>.*)$"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<type>[^:\s]+): (?P<repr>.*?) locals=")

QUESTION = """Run the pytest test
`kedro_qa/context_convert_paths_to_absolute_posix_s5_exceptions/files/testcase.py::TestContextPathExceptions::test_generated_catalog_then_invalid_root`
against this repository. During the test's final call to
`KedroContext._get_catalog`, its direct invocation of the exact function
`kedro.framework.context.context._convert_paths_to_absolute_posix` in
`kedro/framework/context/context.py` raises an exception that propagates out of
that target function to `_get_catalog` and then reaches the test's broad
exception handler. What are that propagated exception's type and message?

An invocation means one call of the exact target function, including a
recursive call, and invocations are numbered 1-based in chronological call
order. The requested invocation is unambiguously the direct target invocation
made by the final `_get_catalog` call; do not report any exception outside the
exact target frame, and do not report activity from the earlier successful
`_get_catalog` call or its recursive target invocations. “Propagates out”
means that the exception terminates this target invocation rather than being
caught and suppressed within it.

For the `exception_type` string, use bare `type(exc).__name__` for built-in
exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`). For `exception_message`, use the exact
`str(exc)`, character for character, as a JSON string; do not use `repr(exc)`,
and do not include representation quotes around the message. An empty
exception message would be the empty JSON string `""`, not JSON `null` and
not an omitted key.

The complete answer must be one JSON object with exactly the shape
`{"exception_message": "str", "exception_type": "str"}`. Both values are JSON
strings; the `"str"` values shown in the shape are type placeholders, not
answer values. Include exactly those two keys and no additional fields."""


def _message_from_exception_repr(repr_text: str) -> str:
    try:
        expression = ast.parse(repr_text, mode="eval").body
    except SyntaxError as exc:
        raise RuntimeError(
            f"could not parse exception repr from trace: {repr_text!r}"
        ) from exc
    if not isinstance(expression, ast.Call) or len(expression.args) != 1:
        raise RuntimeError(f"unexpected exception repr shape: {repr_text!r}")
    argument = expression.args[0]
    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
        raise RuntimeError(f"exception repr does not contain one string: {repr_text!r}")
    return argument.value


def _exception_type_name(name: str) -> str:
    candidate = getattr(builtins, name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__
    raise RuntimeError(
        "trace does not provide a module-qualified name for non-built-in "
        f"exception type {name!r}"
    )


def _read_exception(trace_path: Path) -> dict[str, str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    exceptions: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file").replace("\\", "/").endswith(
                f"/{TARGET_FILE}"
            )
        ):
            continue
        target_events += 1
        if match.group("event") != "exception":
            continue
        exception_match = EXCEPTION_RE.search(match.group("details"))
        if exception_match is None:
            raise RuntimeError(f"malformed target exception event: {raw_line}")
        exceptions.append(
            (exception_match.group("type"), exception_match.group("repr"))
        )

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if len(exceptions) != 1:
        raise RuntimeError(
            f"expected exactly one target exception event, found {len(exceptions)}"
        )

    raw_type, raw_repr = exceptions[0]
    return {
        "exception_message": _message_from_exception_repr(raw_repr),
        "exception_type": _exception_type_name(raw_type),
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": _read_exception(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
