from __future__ import annotations

import argparse
import ast
import builtins
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/decorators.py"
SOURCE_FILE = Path("src/click/decorators.py")
TARGET_FUNC = "click.decorators.version_option.<locals>.callback"

QUESTION = """Run the single pytest test `click_qa/decorators_callback_s5_exceptions/files/testcase.py::TestGeneratedVersionCallbacks::test_programmatic_package_resolution_paths`. Consider every invocation, during that test method, of the target function `click.decorators.version_option.<locals>.callback` (the nested function referred to as `version_option.callback`) in the repository-relative file `src/click/decorators.py`.

Among those invocations, select the chronologically last invocation in which an exception raised by an explicit `raise` statement lexically belonging to the target callback's own body propagates out of that callback frame to its caller. An invocation means one Python call of the target function, numbered from 1 in chronological call order. “Propagates out” means that the exception leaves the target frame; it still counts when the test method subsequently catches it. An exception originating in a called function is not raised by the callback's own explicit `raise`, and an exception caught inside the callback is excluded. Identify an explicit `raise` by the absolute 1-based line number in `src/click/decorators.py` where that callback-owned `raise` statement begins (the line containing the `raise` keyword). For a multi-line raise statement, this is its beginning line, not a later continuation line; decorator, `def`, and docstring lines are not raise-statement lines.

Report the exception that propagates from that selected invocation as exactly `{"exception_message": "str", "exception_type": "str"}`. `exception_message` is the exact `str(exc)`, character for character, with no quoting, truncation, or whitespace normalization; an empty message would be the JSON string `""`, never JSON null or an omitted key. For `exception_type`, use bare `type(exc).__name__` for built-in exceptions (e.g. `LookupError`, never `builtins.LookupError`), and `module.QualName` for all others (e.g. `acme.errors.WidgetFault`), where the latter is `type(exc).__module__ + "." + type(exc).__qualname__`. Emit ordinary JSON strings, not Python `repr()` strings. There is exactly one selected exception, so no sorting or deduplication is performed, and both keys must always be present."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def callback_raise_lines(source_path: Path) -> set[int]:
    if not source_path.exists():
        fail(f"target source does not exist: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    version_option = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "version_option"
        ),
        None,
    )
    if version_option is None:
        fail("could not locate version_option in target source")

    callback = next(
        (
            node
            for node in version_option.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "callback"
        ),
        None,
    )
    if callback is None:
        fail("could not locate nested callback in version_option")

    lines = {node.lineno for node in ast.walk(callback) if isinstance(node, ast.Raise)}
    if not lines:
        fail("target callback contains no explicit raise statements")
    return lines


def exception_message_from_repr(type_name: str, value_repr: str) -> str:
    try:
        expression = ast.parse(value_repr, mode="eval").body
    except SyntaxError as error:
        fail(f"could not parse exception repr {value_repr!r}: {error}")

    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
        fail(f"unsupported exception repr: {value_repr!r}")
    if expression.func.id != type_name or expression.keywords:
        fail(f"exception repr does not match type {type_name!r}: {value_repr!r}")

    try:
        arguments = [ast.literal_eval(argument) for argument in expression.args]
    except (ValueError, SyntaxError) as error:
        fail(f"exception repr has non-literal arguments: {value_repr!r}: {error}")

    exception_class = getattr(builtins, type_name, None)
    if not isinstance(exception_class, type) or not issubclass(
        exception_class, BaseException
    ):
        fail(
            "trace records only an unqualified exception name, but selected "
            f"exception {type_name!r} is not a built-in exception"
        )
    return str(exception_class(*arguments))


def parse_trace(trace_path: Path) -> dict[str, str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    raise_lines = callback_raise_lines(SOURCE_FILE)
    event_pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
        r"(?P<rest>.*)$"
    )
    exception_pattern = re.compile(
        r"^ exc=(?P<type>[^: ]+): (?P<repr>.*?) locals=.*$"
    )
    target_events = 0
    active_invocation = 0
    invocation_count = 0
    candidates: list[tuple[int, str, str]] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue

        filename = match.group("file").replace("\\", "/")
        function = match.group("func")
        if not filename.endswith(TARGET_FILE_SUFFIX) or function != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))
        if event == "call":
            if active_invocation:
                fail("unexpected recursive or overlapping target invocation")
            invocation_count += 1
            active_invocation = invocation_count
        elif event == "exception" and line_number in raise_lines:
            if not active_invocation:
                fail("callback-owned raise occurred outside an active invocation")
            exception_match = exception_pattern.match(match.group("rest"))
            if exception_match is None:
                fail(f"could not parse exception payload: {raw_line}")
            type_name = exception_match.group("type")
            value_repr = exception_match.group("repr")
            candidates.append((active_invocation, type_name, value_repr))
        elif event == "return":
            if not active_invocation:
                fail("target return occurred without an active invocation")
            active_invocation = 0

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count == 0:
        fail("trace contains no target call events")
    if active_invocation:
        fail("trace ended with an active target invocation")
    if not candidates:
        fail("trace contains no exception event on a callback-owned raise statement")

    _invocation, raw_type, value_repr = candidates[-1]
    exception_class = getattr(builtins, raw_type, None)
    if not isinstance(exception_class, type) or not issubclass(
        exception_class, BaseException
    ):
        fail(f"cannot qualify non-built-in exception type from trace: {raw_type!r}")

    return {
        "exception_message": exception_message_from_repr(raw_type, value_repr),
        "exception_type": raw_type,
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "exception_message": "str",
            "exception_type": "str",
        },
        "oracle_answer": parse_trace(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote oracle to {arguments.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
