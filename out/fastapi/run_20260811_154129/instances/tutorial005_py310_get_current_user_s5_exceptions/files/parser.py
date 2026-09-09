#!/usr/bin/env python3
import argparse
import ast
import builtins
import importlib
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "docs_src/security/tutorial005_py310.py"
TARGET_FUNC = "docs_src.security.tutorial005_py310.get_current_user"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)
EXCEPTION_RE = re.compile(
    r"\bevent=exception exc=(?P<type>[A-Za-z_][A-Za-z0-9_]*):"
)

QUESTION = """Run exactly this pytest test against the repository:
`fastapi_qa/tutorial005_py310_get_current_user_s5_exceptions/files/testcase.py::TestCurrentUserExceptionMatrix::test_generated_tokens_and_scope_walks`.
Pytest ids here use the repo-relative
`path/to/test_file.py::TestClass::test_method` format (for example,
`tests/test_demo.py::TestDemo::test_case`).

Across the entire test run, consider every invocation of
`docs_src.security.tutorial005_py310.get_current_user`, defined in
`docs_src/security/tutorial005_py310.py`. An invocation is one entry into
exactly that function's frame, numbered 1-based in chronological call-entry
order. Frames for callers, callees, comprehensions, and generators are not
target invocations.

What is the set of exception types caught by the `except
(InvalidTokenError, ValidationError)` handler at line 127 inside those target
invocations? An exception counts as caught when it is raised by a statement
in that handler's `try` suite, or propagates from a callee to such a statement
in the exact target frame, and its runtime type matches that handler so
control transfers to the handler. Count the target-frame occurrence once;
do not count occurrences only in callee or caller frames. Do not include an
exception that arises outside that `try` suite, an exception fully handled
inside a callee, or the replacement exception raised by the handler at line
128 and propagated out of the target.

Line numbers in this question are absolute, 1-based source line numbers in
the named file as it exists in the repository. For a multi-line statement or
call, its exception point is the line where that executed statement or
expression begins. Decorator and `def` lines are not part of the `try` suite.

Use this exception type naming convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`). Remove duplicates globally by the
complete formatted type-name string, then sort the remaining strings in
ascending lexicographic order using Python's default string ordering
(Unicode code-point order); there are no further tie-breakers.

Return exactly one JSON object with this shape:
`{"caught_exception_kinds": ["str"]}`. The value is a JSON array of strings,
not a Python container representation; each element is the formatted runtime
type name described above. The key is always present. If no exception
qualifies, the array is `[]`, not JSON `null`, an empty string, or an omitted
key. Exception messages, source line numbers, invocation numbers, and counts
are not part of the answer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def handler_classes_and_try_lines(
    source_path: Path, module: object
) -> tuple[tuple[type[BaseException], ...], set[int]]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        fail(f"could not parse target source {source_path}: {error}")

    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "get_current_user"
    ]
    if len(functions) != 1:
        fail(f"expected one get_current_user definition, found {len(functions)}")

    tries = [node for node in ast.walk(functions[0]) if isinstance(node, ast.Try)]
    if len(tries) != 1 or len(tries[0].handlers) != 1:
        fail("expected exactly one try statement with one handler in target")
    target_try = tries[0]
    handler_type = target_try.handlers[0].type
    type_nodes = handler_type.elts if isinstance(handler_type, ast.Tuple) else [handler_type]

    classes: list[type[BaseException]] = []
    for node in type_nodes:
        if not isinstance(node, ast.Name):
            fail("target exception handler contains a non-name exception type")
        exception_class = getattr(module, node.id, None)
        if (
            not isinstance(exception_class, type)
            or not issubclass(exception_class, BaseException)
        ):
            fail(f"could not resolve handler exception class {node.id!r}")
        classes.append(exception_class)

    try_lines: set[int] = set()
    for statement in target_try.body:
        end_line = getattr(statement, "end_lineno", statement.lineno)
        try_lines.update(range(statement.lineno, end_line + 1))
    if not try_lines:
        fail("target try suite has no source lines")
    return tuple(classes), try_lines


def all_exception_subclasses(
    roots: tuple[type[BaseException], ...],
) -> dict[str, type[BaseException]]:
    by_name: dict[str, type[BaseException]] = {}
    pending = list(roots)
    seen: set[type[BaseException]] = set()
    while pending:
        exception_class = pending.pop()
        if exception_class in seen:
            continue
        seen.add(exception_class)
        existing = by_name.get(exception_class.__name__)
        if existing is not None and existing is not exception_class:
            fail(
                "ambiguous caught exception short name "
                f"{exception_class.__name__!r}"
            )
        by_name[exception_class.__name__] = exception_class
        pending.extend(exception_class.__subclasses__())
    return by_name


def format_exception_type(exception_class: type[BaseException]) -> str:
    if exception_class.__module__ == builtins.__name__:
        return exception_class.__name__
    return f"{exception_class.__module__}.{exception_class.__qualname__}"


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events: list[tuple[str, int, str]] = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        traced_file = match.group("file").replace("\\", "/")
        if not traced_file.endswith(TARGET_FILE):
            fail(f"target event came from unexpected file: {traced_file}")
        target_events.append(
            (match.group("event"), int(match.group("line")), raw_line)
        )

    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    call_count = sum(event == "call" for event, _line, _raw in target_events)
    line_count = sum(event == "line" for event, _line, _raw in target_events)
    if call_count == 0:
        fail(f"trace contains no invocations of {TARGET_FUNC}")
    if line_count == 0:
        fail(f"trace contains no executed lines in {TARGET_FUNC}")

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")
    module = importlib.import_module("docs_src.security.tutorial005_py310")
    handler_classes, try_lines = handler_classes_and_try_lines(source_path, module)
    caught_classes = all_exception_subclasses(handler_classes)

    caught_names: set[str] = set()
    caught_event_count = 0
    for event, line_number, raw_line in target_events:
        if event != "exception" or line_number not in try_lines:
            continue
        match = EXCEPTION_RE.search(raw_line)
        if match is None:
            fail(f"target exception event has no parseable type: {raw_line}")
        exception_class = caught_classes.get(match.group("type"))
        if exception_class is None:
            continue
        caught_event_count += 1
        caught_names.add(format_exception_type(exception_class))

    if caught_event_count == 0:
        fail("trace contains no exception caught by the target handler")
    if len(caught_names) < 2:
        fail(
            "caught-exception answer is insufficiently rich: "
            f"{sorted(caught_names)!r}"
        )

    output = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": sorted(caught_names)},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote caught-exception oracle to {out_path}")


if __name__ == "__main__":
    main()
