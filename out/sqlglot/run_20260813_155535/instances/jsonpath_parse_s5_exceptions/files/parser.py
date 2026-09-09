import argparse
import ast
import builtins
import importlib
import json
import re
from pathlib import Path


TARGET_FILE = "sqlglot/jsonpath.py"
TARGET_FUNC = "sqlglot.jsonpath.parse"
EVENT_RE = re.compile(
    r"(?P<path>\S*sqlglot/jsonpath\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(
    r"\bexc=(?P<exception_type>[^:\s]+): (?P<exception_repr>.*?) locals="
)

QUESTION = """Run only the pytest test
`sqlglot_qa/jsonpath_parse_s5_exceptions/files/testcase.py::TestJSONPathParseExceptions::test_generated_path_with_terminal_separator`
from `sqlglot_qa/jsonpath_parse_s5_exceptions/files/testcase.py`. During that
test, consider the sole direct invocation of `sqlglot.jsonpath.parse` in
`sqlglot/jsonpath.py`.

What are the type and message of the exception that propagates out of that
target invocation and reaches its direct caller? "Propagates out" means that
the exception leaves the exact `sqlglot.jsonpath.parse` frame without being
handled there. Exceptions raised and handled wholly in a callee do not count.
An invocation is one call of the target function, numbered 1-based in
chronological order during this test run; the question covers invocation 1,
which is the only invocation.

Exception type naming MUST use this convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g. `package.errors.CustomError`). Here,
`module.QualName` is exactly
`f"{type(exc).__module__}.{type(exc).__qualname__}"`. The exception message is
the exact `str(exc)`, character for character, with no `repr()` quoting,
escaping, truncation, or whitespace normalization; an empty message would be
the empty JSON string `""`, not JSON `null` and not an omitted key.

Return exactly
`{"exception_message": <JSON string>, "exception_type": <JSON string>}`.
These are scalar fields, so no sorting or deduplication is performed, and JSON
object member order is not semantically significant."""


def resolve_exception_type(raw_name):
    builtin = getattr(builtins, raw_name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return builtin, builtin.__name__

    target_module = importlib.import_module("sqlglot.jsonpath")
    candidates = {
        value
        for value in vars(target_module).values()
        if isinstance(value, type)
        and issubclass(value, BaseException)
        and value.__name__ == raw_name
    }
    if len(candidates) != 1:
        names = sorted(f"{value.__module__}.{value.__qualname__}" for value in candidates)
        raise RuntimeError(
            f"cannot uniquely resolve non-built-in exception type {raw_name!r}: {names!r}"
        )

    exception_type = candidates.pop()
    return (
        exception_type,
        f"{exception_type.__module__}.{exception_type.__qualname__}",
    )


def exception_args(exception_repr, raw_name):
    try:
        expression = ast.parse(exception_repr, mode="eval").body
    except SyntaxError as error:
        raise RuntimeError(
            f"cannot parse exception repr (possibly truncated): {exception_repr!r}"
        ) from error

    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id != raw_name
        or expression.keywords
    ):
        raise RuntimeError(f"unsupported exception repr: {exception_repr!r}")

    try:
        return [ast.literal_eval(argument) for argument in expression.args]
    except (ValueError, TypeError, SyntaxError) as error:
        raise RuntimeError(f"non-literal exception arguments: {exception_repr!r}") from error


def parse_trace(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if not trace_path.is_file() or trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    exceptions = []
    for trace_line_number, line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), 1
    ):
        event_match = EVENT_RE.search(line)
        if not event_match or event_match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        if event_match.group("event") != "exception":
            continue

        exception_match = EXCEPTION_RE.search(line)
        if not exception_match:
            raise RuntimeError(
                f"malformed target exception event at trace line {trace_line_number}"
            )

        raw_name = exception_match.group("exception_type")
        exception_type, formatted_type = resolve_exception_type(raw_name)
        args = exception_args(exception_match.group("exception_repr"), raw_name)
        exceptions.append(
            {
                "exception_message": str(exception_type(*args)),
                "exception_type": formatted_type,
            }
        )

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not exceptions:
        raise RuntimeError(f"trace contains zero exception events for {TARGET_FUNC}")
    if len(exceptions) != 1:
        raise RuntimeError(
            f"expected exactly one exception propagated through {TARGET_FUNC}, "
            f"found {len(exceptions)}"
        )

    return exceptions[0]


def main():
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
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
