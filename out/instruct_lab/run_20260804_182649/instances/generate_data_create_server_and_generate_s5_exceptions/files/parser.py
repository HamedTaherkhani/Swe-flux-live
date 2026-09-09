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


TARGET_FILE = "src/instructlab/data/generate_data.py"
TARGET_FUNC = "instructlab.data.generate_data.create_server_and_generate"
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
    r"(?: exc=(?P<exc_type>[^:\s]+):)?"
)


QUESTION = (
    "Run only the pytest test "
    "`instruct_lab_qa/generate_data_create_server_and_generate_s5_exceptions/"
    "files/testcase.py::TestGeneratedDataFailureMatrix::"
    "test_public_entry_point_handles_runtime_failure_matrix` against this repository. "
    "Across the complete selected test run, what is the set of concrete runtime "
    "exception types caught inside "
    "`instructlab.data.generate_data.create_server_and_generate` in "
    "`src/instructlab/data/generate_data.py`? An exception is \"caught inside\" "
    "only when that exception instance produces an exception event in this exact "
    "function's frame and runtime control then transfers into the suite of one of "
    "this function's own `except` clauses. Include exceptions originating in a "
    "callee when they reach and are handled by such a clause. Exclude exception "
    "events in every other function's frame, exceptions that merely propagate out "
    "of the target, and exceptions raised by an `except` suite but not handled "
    "again by another `except` clause in the same target invocation. Consider every "
    "target invocation made by the selected test. An invocation is one runtime call "
    "of exactly this function during the test, numbered 1-based in chronological "
    "call order; calls of other functions do not count. Use the concrete type of "
    "each caught exception instance, not the type expression written on its handler. "
    "Exception type naming MUST use this convention: bare `type(exc).__name__` for "
    "built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and "
    "`module.QualName` for all others (e.g. `acme.errors.WidgetFailure`). Combine "
    "all invocations into one set, normalize each type to that naming convention, "
    "remove duplicates by the complete normalized string, and sort the remaining "
    "strings in ascending lexicographic Unicode code-point order. There is no "
    "secondary tie-breaker because duplicates are removed. Return exactly one JSON "
    "object with the single key `caught_exception_kinds`; its value must be a "
    "non-empty JSON array of JSON strings in that order. Each item is the normalized "
    "type name, not `str(exc)`, `repr(exc)`, or an exception message; no item may be "
    "null, empty, omitted, or Python-repr formatted."
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


@dataclass(frozen=True)
class Handler:
    body_lines: frozenset[int]


def flatten_handler_types(node):
    if node is None:
        return ()
    if isinstance(node, ast.Tuple):
        return tuple(
            item
            for element in node.elts
            for item in flatten_handler_types(element)
        )
    return (node,)


def import_bindings(tree):
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                bindings[local_name] = ("module", alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                bindings[alias.asname or alias.name] = (node.module, alias.name)
    return bindings


def resolve_expression(node, bindings):
    if isinstance(node, ast.Name):
        if node.id in bindings:
            module_name, attribute = bindings[node.id]
            if module_name == "module":
                return importlib.import_module(attribute)
            return getattr(importlib.import_module(module_name), attribute)
        if hasattr(builtins, node.id):
            return getattr(builtins, node.id)
        fail(f"cannot resolve exception name {node.id!r}")
    if isinstance(node, ast.Attribute):
        return getattr(resolve_expression(node.value, bindings), node.attr)
    fail(f"unsupported exception expression: {ast.dump(node)}")


def normalized_type_name(exception_type):
    if exception_type.__module__ == "builtins":
        return exception_type.__name__
    return f"{exception_type.__module__}.{exception_type.__qualname__}"


def target_metadata(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "create_server_and_generate"
        ),
        None,
    )
    if function is None:
        fail(f"target function not found in {source_path}")

    bindings = import_bindings(function)
    handlers = []
    known_nonbuiltins = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.ExceptHandler):
            continue
        handlers.append(
            Handler(
                body_lines=frozenset(
                    line
                    for statement in node.body
                    for line in range(statement.lineno, statement.end_lineno + 1)
                )
            )
        )
        for type_node in flatten_handler_types(node.type):
            resolved = resolve_expression(type_node, bindings)
            if not isinstance(resolved, type) or not issubclass(
                resolved, BaseException
            ):
                fail(f"handler is not an exception type: {ast.dump(type_node)}")
            if resolved.__module__ != "builtins":
                known_nonbuiltins.setdefault(resolved.__name__, set()).add(
                    normalized_type_name(resolved)
                )

    if not handlers:
        fail(f"target function has no exception handlers in {source_path}")

    resolved_nonbuiltins = {}
    for simple_name, qualified_names in known_nonbuiltins.items():
        if len(qualified_names) != 1:
            fail(
                f"ambiguous non-built-in exception name {simple_name!r}: "
                f"{sorted(qualified_names)!r}"
            )
        resolved_nonbuiltins[simple_name] = next(iter(qualified_names))
    return handlers, resolved_nonbuiltins


def parse_trace(trace_path, handlers, known_nonbuiltins):
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
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    builtin_exceptions = {
        name: value
        for name, value in vars(builtins).items()
        if isinstance(value, type) and issubclass(value, BaseException)
    }
    caught = set()
    for index, (event, _line, simple_name) in enumerate(events):
        if event != "exception" or simple_name is None:
            continue
        enters_handler = False
        for later_event, later_line, _later_name in events[index + 1 :]:
            if later_event in {"call", "return", "exception"}:
                break
            if any(later_line in handler.body_lines for handler in handlers):
                enters_handler = True
                break
        if not enters_handler:
            continue
        if simple_name in builtin_exceptions:
            caught.add(normalized_type_name(builtin_exceptions[simple_name]))
        elif simple_name in known_nonbuiltins:
            caught.add(known_nonbuiltins[simple_name])
        else:
            fail(f"cannot normalize caught exception type {simple_name!r}")

    if not caught:
        fail("no exception transferred control into a target exception handler")
    return sorted(caught)


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")
    handlers, known_nonbuiltins = target_metadata(source_path)
    answer = parse_trace(Path(args.trace_log), handlers, known_nonbuiltins)
    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": answer},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
