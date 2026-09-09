#!/usr/bin/env python3
import argparse
import ast
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "lark/parsers/lalr_parser.py"
TARGET_FUNC = "lark.parsers.lalr_parser._Parser.parse_from_state"
EVENT_RE = re.compile(
    r" (?P<path>\S*lark/parsers/lalr_parser\.py):(?P<line>\d+) "
    r"lark\.parsers\.lalr_parser\._Parser\.parse_from_state "
    r"event=(?P<event>call|line|return|exception)"
    r"(?: exc=(?P<exc_type>[^:\s]+): .*)?"
)

QUESTION = """Run the single pytest method `ParseFromStateExceptionBehaviorTests.test_generated_failures_across_parser_runs` in `lark_qa/lalr_parser_parse_from_state_s5_exceptions/files/testcase.py`. Across all invocations of `lark.parsers.lalr_parser._Parser.parse_from_state` in `lark/parsers/lalr_parser.py` made by that method, what set of exception types is caught inside the target function?

An invocation means one call of the target function during this test method, numbered 1-based in chronological call order. An exception counts as caught inside the target only when it is delivered to the target's frame while executing its `try` suite and execution then enters the first executable statement of a matching `except` suite in that same frame. Count it even if the handler later re-raises it. Exclude exceptions that merely propagate out without entering a target handler, and exclude exceptions caught only by the test or another function. Source line numbers used to identify handler entry are absolute, 1-based line numbers in the named repository file; for a multi-line statement, use the line where that statement or expression begins. Decorator, `def`, and docstring lines do not count as handler-suite entry unless Python actually executes them as that suite's first statement.

Return exactly `{"caught_exception_kinds": ["str"]}`. The list is the union across every target invocation: remove duplicate type names, then sort the remaining strings in ascending Python lexicographic (Unicode code-point) order. Exception type naming MUST use this convention: bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never `builtins.ValueError`), and `module.QualName` for all others (e.g. `haystack.core.errors.PipelineError`). Each list element is that convention's plain string, represented as a JSON string; an empty set would be `[]`, not `null` or an omitted key."""


def handler_lines(source_path: Path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "parse_from_state":
            target = node
            break
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    handlers = [
        handler
        for handler in ast.walk(target)
        if isinstance(handler, ast.ExceptHandler) and handler.body
    ]
    entries = {handler.body[0].lineno for handler in handlers}
    if not entries:
        raise RuntimeError("target function contains no exception handlers")
    return entries, {handler.lineno for handler in handlers}


def format_exception_type(short_name: str) -> str:
    candidate = getattr(builtins, short_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__

    import lark.exceptions as lark_exceptions

    matches = []
    for value in vars(lark_exceptions).values():
        if (
            isinstance(value, type)
            and issubclass(value, BaseException)
            and value.__name__ == short_name
        ):
            matches.append(f"{value.__module__}.{value.__qualname__}")
    matches = sorted(set(matches))
    if len(matches) != 1:
        raise RuntimeError(
            f"cannot unambiguously resolve non-built-in exception type {short_name!r}"
        )
    return matches[0]


def parse_trace(trace_path: Path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    records = []
    source_path = None
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        record = match.groupdict()
        record["line"] = int(record["line"])
        records.append(record)
        source_path = Path(record["path"])

    if not records:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if source_path is None or not source_path.exists():
        raise RuntimeError("could not locate target source from target trace events")

    entries, clause_lines = handler_lines(source_path)
    caught = set()
    pending = None
    for record in records:
        event = record["event"]
        if event == "exception":
            exc_type = record.get("exc_type")
            if not exc_type:
                raise RuntimeError("target exception event has no parseable exception type")
            pending = exc_type
        elif event == "line":
            if pending is not None and record["line"] in entries:
                caught.add(format_exception_type(pending))
                pending = None
            elif pending is not None and record["line"] not in clause_lines:
                pending = None
        elif event in {"call", "return"}:
            pending = None

    if not caught:
        raise RuntimeError("no exceptions caught inside the target function were found")
    return sorted(caught)


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = {"caught_exception_kinds": parse_trace(Path(args.trace_log))}
    document = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": answer,
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {output_path}")


if __name__ == "__main__":
    main()
