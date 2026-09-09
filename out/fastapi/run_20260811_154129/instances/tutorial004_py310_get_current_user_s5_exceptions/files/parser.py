#!/usr/bin/env python3
import argparse
import ast
import builtins
import importlib
import json
import re
from pathlib import Path


TARGET_FILE = "docs_src/security/tutorial004_py310.py"
TARGET_MODULE = "docs_src.security.tutorial004_py310"
TARGET_FUNCTION = "get_current_user"
TARGET_QUALNAME = f"{TARGET_MODULE}.{TARGET_FUNCTION}"
TEST_ID = (
    "fastapi_qa/tutorial004_py310_get_current_user_s5_exceptions/files/"
    "testcase.py::TestGetCurrentUserExceptionKinds::test_seeded_token_matrix"
)

QUESTION = f"""During the pytest test `{TEST_ID}`, consider every direct invocation of `docs_src.security.tutorial004_py310.get_current_user` in `docs_src/security/tutorial004_py310.py`. An invocation is one `call` of that function during this test, numbered 1-based in chronological order.

Report the set of concrete exception types caught by the function's `except InvalidTokenError` clause whose `except` keyword begins at absolute, 1-based line 104 of that repository file. Here, an exception counts as caught only when it is raised while evaluating the lexical `try` suite in that invocation and control subsequently enters that specific handler in the same invocation. Include the concrete runtime type of the original exception that caused entry into the handler; do not include the handler's declared base type merely because it appears in the source, and do not include the `HTTPException` raised by the handler and propagated out of the function. Combine all invocations, remove duplicate type names, and sort the remaining strings in ascending lexicographic order by their complete emitted strings (Python/Unicode code-point order); there is no secondary tie-breaker because duplicates are removed.

Exception type naming MUST use this convention: bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and `module.QualName` for all others (e.g. `haystack.core.errors.PipelineError`). Return exactly one JSON object with the key `caught_exception_kinds`; its value must be a JSON array of strings in the order just defined. If no exception is caught, use an empty JSON array, not `null` or an omitted key."""

EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    r"(?P<rest>.*)$"
)
EXCEPTION_RE = re.compile(r"\bexc=(?P<name>[A-Za-z_][A-Za-z0-9_]*):")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def find_handler_details(source_path: Path) -> tuple[int, int, int, int, str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_FUNCTION
        ),
        None,
    )
    if function is None:
        fail(f"target function {TARGET_FUNCTION!r} not found in {source_path}")

    for node in ast.walk(function):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if isinstance(handler.type, ast.Name) and handler.type.id == "InvalidTokenError":
                if not node.body or not handler.body:
                    fail("target try suite or exception handler is unexpectedly empty")
                return (
                    handler.lineno,
                    handler.body[0].lineno,
                    min(statement.lineno for statement in node.body),
                    max(statement.end_lineno or statement.lineno for statement in node.body),
                    handler.type.id,
                )
    fail("except InvalidTokenError handler not found in target function")


def caught_type_map(module_name: str, class_name: str) -> dict[str, type]:
    module = importlib.import_module(module_name)
    root = getattr(module, class_name, None)
    if not isinstance(root, type):
        fail(f"{module_name}.{class_name} did not resolve to an exception class")

    classes = {root}
    pending = [root]
    while pending:
        current = pending.pop()
        for child in current.__subclasses__():
            if child not in classes:
                classes.add(child)
                pending.append(child)

    by_name: dict[str, type] = {}
    for exception_class in classes:
        existing = by_name.get(exception_class.__name__)
        if existing is not None and existing is not exception_class:
            fail(f"ambiguous exception class name {exception_class.__name__!r}")
        by_name[exception_class.__name__] = exception_class
    return by_name


def format_exception_type(exception_class: type) -> str:
    if exception_class.__module__ == builtins.__name__:
        return exception_class.__name__
    return f"{exception_class.__module__}.{exception_class.__qualname__}"


def parse_caught_types(trace_path: Path, source_path: Path) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    (
        handler_line,
        handler_body_line,
        try_start,
        try_end,
        caught_class_name,
    ) = find_handler_details(source_path)
    type_map = caught_type_map(TARGET_MODULE, caught_class_name)

    target_events = 0
    invocation_count = 0
    active = False
    pending_exception_name: str | None = None
    caught_names: set[str] = set()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_QUALNAME:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            invocation_count += 1
            active = True
            pending_exception_name = None
            continue
        if not active:
            fail("target event occurred outside a target invocation")

        if event == "exception" and try_start <= line <= try_end:
            exception_match = EXCEPTION_RE.search(match.group("rest"))
            if exception_match is None:
                fail(f"could not parse exception type from trace line: {raw_line}")
            pending_exception_name = exception_match.group("name")
        elif event == "line" and line == handler_body_line:
            if pending_exception_name is None:
                fail(
                    f"handler body after line {handler_line} had no preceding "
                    "exception in the try suite"
                )
            exception_class = type_map.get(pending_exception_name)
            if exception_class is None:
                fail(
                    f"caught exception {pending_exception_name!r} is not "
                    f"{caught_class_name} or one of its loaded subclasses"
                )
            caught_names.add(format_exception_type(exception_class))
            pending_exception_name = None
        elif event == "return":
            active = False
            pending_exception_name = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_QUALNAME}")
    if invocation_count == 0:
        fail(f"trace contains no calls of {TARGET_QUALNAME}")
    if not caught_names:
        fail("trace contains no exceptions caught by the target handler")
    return sorted(caught_names)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    answer = {"caught_exception_kinds": parse_caught_types(args.trace_log, source_path)}
    document = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
