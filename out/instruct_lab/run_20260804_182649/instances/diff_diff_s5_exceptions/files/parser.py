#!/usr/bin/env python3
import argparse
import ast
import builtins
import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TARGET_FILE = "src/instructlab/taxonomy/diff.py"
TARGET_FUNC = "instructlab.taxonomy.diff.diff"
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
    type_nodes: tuple[ast.expr, ...]


def flatten_handler_types(node: ast.expr | None) -> tuple[ast.expr, ...]:
    if node is None:
        return ()
    if isinstance(node, ast.Tuple):
        return tuple(
            item for element in node.elts for item in flatten_handler_types(element)
        )
    return (node,)


def import_bindings(tree: ast.AST) -> dict[str, tuple[str, str | None]]:
    bindings: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                bindings[local_name] = ("module", alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bindings[alias.asname or alias.name] = (node.module, alias.name)
    return bindings


def resolve_expression(
    node: ast.expr, bindings: dict[str, tuple[str, str | None]]
) -> object:
    if isinstance(node, ast.Name):
        if node.id in bindings:
            module_name, attribute = bindings[node.id]
            if module_name == "module":
                return importlib.import_module(str(attribute))
            value = importlib.import_module(module_name)
            for part in str(attribute).split("."):
                value = getattr(value, part)
            return value
        if hasattr(builtins, node.id):
            return getattr(builtins, node.id)
        fail(f"cannot resolve exception name {node.id!r}")
    if isinstance(node, ast.Attribute):
        return getattr(resolve_expression(node.value, bindings), node.attr)
    fail(f"unsupported exception expression: {ast.dump(node)}")


def type_name(exc_type: type[BaseException]) -> str:
    if exc_type.__module__ == "builtins":
        return exc_type.__name__
    return f"{exc_type.__module__}.{exc_type.__qualname__}"


def target_metadata(
    source_path: Path,
) -> tuple[list[Handler], dict[str, str]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "diff"
        ),
        None,
    )
    if function is None:
        fail(f"target function not found in {source_path}")

    bindings = import_bindings(tree)
    handlers: list[Handler] = []
    names_by_simple: dict[str, set[str]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.ExceptHandler):
            continue
        type_nodes = flatten_handler_types(node.type)
        body_lines = frozenset(
            line
            for statement in node.body
            for line in range(statement.lineno, statement.end_lineno + 1)
        )
        handlers.append(Handler(body_lines=body_lines, type_nodes=type_nodes))
        for type_node in type_nodes:
            resolved = resolve_expression(type_node, bindings)
            if not isinstance(resolved, type) or not issubclass(
                resolved, BaseException
            ):
                fail(f"handler expression is not an exception type: {ast.dump(type_node)}")
            names_by_simple.setdefault(resolved.__name__, set()).add(
                type_name(resolved)
            )

    if not handlers:
        fail(f"target function has no exception handlers in {source_path}")

    unique_names = {}
    for simple_name, qualified_names in names_by_simple.items():
        if len(qualified_names) != 1:
            fail(
                f"exception simple name {simple_name!r} is ambiguous: "
                f"{sorted(qualified_names)!r}"
            )
        unique_names[simple_name] = next(iter(qualified_names))
    return handlers, unique_names


def parse_trace(
    trace_path: Path, handlers: list[Handler], names_by_simple: dict[str, str]
) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int, str | None]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if match.group("func") != TARGET_FUNC:
            continue
        if not normalized_file.endswith("/" + TARGET_FILE):
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

    caught: set[str] = set()
    for index, (event, _line, simple_name) in enumerate(events):
        if event != "exception" or simple_name is None:
            continue
        for later_event, later_line, _later_type in events[index + 1 :]:
            if later_event in {"call", "return", "exception"}:
                break
            if any(later_line in handler.body_lines for handler in handlers):
                if simple_name not in names_by_simple:
                    fail(f"caught traced exception type is unresolved: {simple_name}")
                caught.add(names_by_simple[simple_name])
                break

    if not caught:
        fail("no exception event transferred control into a target exception handler")
    return sorted(caught)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    handlers, names_by_simple = target_metadata(source_path)
    answer = parse_trace(Path(args.trace_log), handlers, names_by_simple)
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/diff_diff_s5_exceptions/files/testcase.py::"
        "TestTaxonomyCommandFailureSchedule::"
        "test_cli_command_handles_generated_failure_schedule` against this repository. "
        "Across the complete test run, what is the set of concrete exception types "
        "caught inside `instructlab.taxonomy.diff.diff` in "
        "`src/instructlab/taxonomy/diff.py`? An exception is \"caught inside\" only "
        "when that concrete exception instance reaches this function's frame and "
        "runtime control transfers to the suite of one of this function's own "
        "`except` clauses. Include exceptions originating in callees when they reach "
        "and are handled by such a clause. Exclude exceptions that merely propagate "
        "out of the function and exceptions raised by an `except` suite without being "
        "handled again inside this function. Consider every invocation made during "
        "this one test. An invocation is one runtime call of exactly this function, "
        "numbered 1-based in chronological order; calls of other functions do not "
        "count. Combine all invocations into one set, deduplicate by the final reported "
        "type-name string, and sort those strings in ascending lexicographic Unicode "
        "code-point order. There is no secondary tie-breaker because duplicates are "
        "removed. Exception type naming MUST use this convention: bare "
        "`type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never "
        "`builtins.ValueError`), and `module.QualName` for all others (e.g. "
        "`acme.errors.WidgetFailure`). Use the concrete runtime exception type, not "
        "the type expression written on the matching handler. Return exactly one JSON "
        "object with the single key `caught_exception_kinds`. Its value is a non-empty "
        "JSON array of JSON strings in the stated order. Each string is a type name "
        "under the preceding rule, not `str(exc)`, `repr(exc)`, or an exception "
        "message; no item is null, empty, omitted, or Python-repr formatted."
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
