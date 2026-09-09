#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TARGET_FILE = "src/instructlab/model/serve_backend.py"
TARGET_FUNC = "instructlab.model.serve_backend.serve_backend"
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
    r"(?: exc=(?P<exc_type>[^:\s]+):)?"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


@dataclass(frozen=True)
class Handler:
    body_lines: frozenset[int]
    exception_names: tuple[str, ...]


def imported_names(tree: ast.AST) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def caught_names(type_node: ast.expr | None) -> tuple[str, ...]:
    if type_node is None:
        return ()
    if isinstance(type_node, ast.Tuple):
        return tuple(
            name
            for element in type_node.elts
            for name in caught_names(element)
        )
    if isinstance(type_node, ast.Name):
        return (type_node.id,)
    if isinstance(type_node, ast.Attribute):
        parts = [type_node.attr]
        value = type_node.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
            return (".".join(reversed(parts)),)
    fail(f"unsupported exception handler expression: {ast.dump(type_node)}")


def target_handlers(source_path: Path) -> tuple[list[Handler], dict[str, str]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "serve_backend"
        ),
        None,
    )
    if function is None:
        fail(f"target function not found in {source_path}")

    handlers = []
    for node in ast.walk(function):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body_lines = frozenset(
            line
            for statement in node.body
            for line in range(statement.lineno, statement.end_lineno + 1)
        )
        handlers.append(
            Handler(
                body_lines=body_lines,
                exception_names=caught_names(node.type),
            )
        )
    if not handlers:
        fail(f"target function has no exception handlers in {source_path}")
    return handlers, imported_names(tree)


def qualified_name(simple_name: str, handler: Handler, imports: dict[str, str]) -> str:
    matching = [
        name
        for name in handler.exception_names
        if name.rsplit(".", 1)[-1] == simple_name
    ]
    if len(matching) != 1:
        fail(
            f"cannot uniquely match traced exception {simple_name!r} "
            f"to handler types {handler.exception_names!r}"
        )
    source_name = matching[0]
    root = source_name.split(".", 1)[0]
    if "." not in source_name:
        candidate = getattr(builtins, source_name, None)
        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseException)
            and candidate.__module__ == "builtins"
        ):
            return candidate.__name__
        if source_name in imports:
            return imports[source_name]
    if root in imports:
        return imports[root] + source_name[len(root) :]
    return source_name


def parse_trace(
    trace_path: Path, handlers: list[Handler], imports: dict[str, str]
) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith("/" + TARGET_FILE):
            continue
        events.append(
            (
                match.group("event"),
                int(match.group("line")),
                match.group("exc_type"),
            )
        )

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    caught = set()
    for index, (event, _line, exc_type) in enumerate(events):
        if event != "exception" or not exc_type:
            continue
        for later_event, later_line, _later_exc in events[index + 1 :]:
            if later_event in {"call", "return", "exception"}:
                break
            matching_handlers = [
                handler for handler in handlers if later_line in handler.body_lines
            ]
            if matching_handlers:
                if len(matching_handlers) != 1:
                    fail(f"line {later_line} belongs to multiple exception handlers")
                caught.add(qualified_name(exc_type, matching_handlers[0], imports))
                break

    if not caught:
        fail("target emitted exception events but none entered a target handler")
    return sorted(caught)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    handlers, imports = target_handlers(source_path)
    answer = parse_trace(Path(args.trace_log), handlers, imports)
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/serve_backend_serve_backend_s5_exceptions/files/testcase.py::"
        "TestServeBackendExceptionPaths::"
        "test_cli_serve_handles_backend_failures_before_shutdown` against this "
        "repository. Across the complete test run, what is the set of concrete "
        "exception types caught inside "
        "`instructlab.model.serve_backend.serve_backend` in "
        "`src/instructlab/model/serve_backend.py`? An exception is \"caught inside\" "
        "only when that concrete exception instance reaches this function's frame and "
        "runtime control transfers to the suite of one of this function's own "
        "`except` clauses. Count an exception originating in a callee when it reaches "
        "and is handled by such a clause. Exclude exceptions that merely propagate out "
        "of the function, exceptions raised by an `except` suite without being handled "
        "again inside this function, and exceptions raised by the `finally` suite. "
        "Consider every invocation made during this one test. An invocation is one "
        "runtime call of exactly this function, counted 1-based in chronological order; "
        "calls of other functions do not count, and no invocation is omitted here. "
        "Deduplicate by the reported type-name string, then sort the strings in ascending "
        "lexicographic Unicode code-point order; there is no secondary tie-breaker because "
        "duplicates are removed. Exception type naming MUST use this convention: bare "
        "`type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never "
        "`builtins.ValueError`), and `module.QualName` for all others (e.g. "
        "`acme.errors.WidgetFailure`). Return exactly one JSON object with the single "
        "key `caught_exception_kinds`. Its value is a non-empty JSON array of JSON "
        "strings in the stated order. The strings are type names under the preceding "
        "rule, not `str(exc)`, `repr(exc)`, or exception messages; no entry is null, "
        "empty, omitted, or Python-repr formatted."
    )
    payload = {
        "question_kind": "S5_Exceptions",
        "question": question,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": answer},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
