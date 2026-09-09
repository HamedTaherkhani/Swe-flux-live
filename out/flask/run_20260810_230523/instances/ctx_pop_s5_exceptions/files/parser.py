#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/flask/ctx.py"
TARGET_FUNC = "flask.ctx.AppContext.pop"

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/flask/ctx\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    r"(?: exc=(?P<exc_type>[^:\s]+):.*?)? locals="
)

QUESTION = """Run the pytest test
`flask_qa/ctx_pop_s5_exceptions/files/testcase.py::TestAppContextPopExceptions::test_seeded_request_resource_failures`
against this repository. Across the complete run of that named test, what is
the set of exception types caught inside `flask.ctx.AppContext.pop` in
`src/flask/ctx.py` by the `_CollectErrors` context managers lexically present
in that function?

An exception counts as caught inside the target exactly when it propagates
into the active `flask.ctx.AppContext.pop` frame from a statement in the
protected suite (the body) of one of that function's
`with collect_errors:` statements, and that statement's context-manager exit
suppresses it so execution continues after the `with` statement. Count such
events from every call of the exact target function during the named test.
Do not count an exception handled wholly within a callee, an exception from
another function or frame, or the aggregate exception propagated out by the
final `collect_errors.raise_any(...)` call.

Report distinct exception types only: remove duplicates regardless of which
protected suite or target call produced them. Sort the resulting strings in
ascending lexicographic order by Unicode code point, using ordinary Python
string ordering; after deduplication there are no ordering ties.

Exception type naming MUST use this convention: bare `type(exc).__name__` for
built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and
`module.QualName` for all others (e.g.
`haystack.core.errors.PipelineError`). Exception messages and exception
values are not reported, so no `str`, `repr`, empty-string, or null
serialization convention applies.

Return exactly one JSON object with the single key
`caught_exception_kinds`. Its value must be a JSON list of strings ordered
as specified above."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def protected_lines(source_path: Path) -> set[int]:
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = None

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AppContext":
            target = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "pop"
                ),
                None,
            )
            break

    if target is None:
        fail("could not locate AppContext.pop in target source")

    lines: set[int] = set()
    matching_withs = 0

    for node in ast.walk(target):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if not any(
            isinstance(item.context_expr, ast.Name)
            and item.context_expr.id == "collect_errors"
            for item in node.items
        ):
            continue

        matching_withs += 1
        for statement in node.body:
            for child in ast.walk(statement):
                if hasattr(child, "lineno"):
                    start = child.lineno
                    end = getattr(child, "end_lineno", start)
                    lines.update(range(start, end + 1))

    if matching_withs == 0 or not lines:
        fail("AppContext.pop contains no protected collect_errors suites")

    return lines


def normalize_exception_type(raw_name: str) -> str:
    value = getattr(builtins, raw_name, None)
    if isinstance(value, type) and issubclass(value, BaseException):
        return value.__name__
    fail(
        "encountered a non-built-in exception type whose module and qualname "
        f"are unavailable in the trace: {raw_name}"
    )


def parse_trace(trace_path: Path, source_path: Path) -> list[str]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    caught_lines = protected_lines(source_path)
    target_events = 0
    kinds: set[str] = set()

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.search(raw_line)
            if match is None or match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            if match.group("event") != "exception":
                continue
            if int(match.group("line")) not in caught_lines:
                continue

            raw_name = match.group("exc_type")
            if not raw_name:
                fail("target exception event has no parseable exception type")
            kinds.add(normalize_exception_type(raw_name))

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not kinds:
        fail("trace contains no exceptions caught in protected target suites")

    return sorted(kinds)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {
            "caught_exception_kinds": parse_trace(
                args.trace_log, Path.cwd() / TARGET_FILE
            )
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

