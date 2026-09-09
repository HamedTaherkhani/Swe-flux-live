#!/usr/bin/env python3
"""Parse trace logs for loaders_get_source_m5_exceptions (M5_Exceptions)."""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/loaders.py"
TARGET_FUNC = "jinja2.loaders.PackageLoader.get_source"
TEST_CLASS = "LoadersGetSourceM5ExceptionsTest"
TEST_FILE = "jinja_qa/loaders_get_source_m5_exceptions/files/testcase.py"

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})$"
)

BUILTIN_EXCEPTION_NAMES = {
    name
    for name in dir(builtins)
    if isinstance(getattr(builtins, name), type)
    and issubclass(getattr(builtins, name), BaseException)
}

NON_BUILTIN_EXCEPTION_TYPES = {
    "TemplateNotFound": "jinja2.exceptions.TemplateNotFound",
}


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _parse_locals(raw_locals: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw_locals)
    except (SyntaxError, ValueError) as exc:
        _fail(f"unable to parse locals dict: {raw_locals!r} ({exc})")
    if not isinstance(parsed, dict):
        _fail(f"locals payload is not a dict: {raw_locals!r}")
    return {str(key): str(value) for key, value in parsed.items()}


def _parse_trace_line(raw_line: str) -> dict[str, object] | None:
    if raw_line.startswith("[TRACE]"):
        return None
    match = TRACE_LINE_RE.match(raw_line.strip())
    if not match:
        return None
    return {
        "file": _normalize_file(match.group("file")),
        "lineno": int(match.group("lineno")),
        "func": match.group("func"),
        "event": match.group("event"),
        "exc": match.group("exc"),
        "locals": _parse_locals(match.group("locals")),
    }


def _load_target_events(trace_log: Path) -> list[dict[str, object]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["file"] == TARGET_FILE and parsed["func"] == TARGET_FUNC:
            events.append(parsed)

    if not events:
        _fail(
            f"no trace events for {TARGET_FUNC} in {TARGET_FILE}; "
            f"check TRACE_FILE/TRACE_FUNC configuration"
        )
    return events


def _discover_test_method_ids(testcase_path: Path) -> list[str]:
    source = testcase_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(testcase_path))
    method_names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TEST_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    method_names.append(item.name)
    method_names.sort()
    if not method_names:
        _fail(f"no test methods found in class {TEST_CLASS}")
    return [
        f"{TEST_FILE}::{TEST_CLASS}::{method_name}" for method_name in method_names
    ]


def _extract_exception_type_name(exc_field: str) -> str:
    if not exc_field:
        _fail("exception event missing exc= payload")
    name = exc_field.split(":", 1)[0].strip()
    if not name:
        _fail(f"unable to parse exception type from exc payload: {exc_field!r}")
    return name


def _format_exception_type_name(raw_name: str) -> str:
    if raw_name in BUILTIN_EXCEPTION_NAMES:
        return raw_name
    if raw_name in NON_BUILTIN_EXCEPTION_TYPES:
        return NON_BUILTIN_EXCEPTION_TYPES[raw_name]
    return raw_name


def _exception_type_counts(events: list[dict[str, object]]) -> list[dict[str, int | str]]:
    counts: dict[str, int] = {}
    for event in events:
        if event["event"] != "exception":
            continue
        raw_name = _extract_exception_type_name(str(event["exc"]))
        formatted = _format_exception_type_name(raw_name)
        counts[formatted] = counts.get(formatted, 0) + 1

    if not counts:
        _fail(
            f"no exception observations recorded for {TARGET_FUNC}; "
            f"expected at least one exception event"
        )

    return [
        {"exception_type": exc_type, "count": counts[exc_type]}
        for exc_type in sorted(counts)
    ]


def _build_question(test_method_ids: list[str]) -> str:
    method_list = "; ".join(f"`{method_id}`" for method_id in test_method_ids)
    return (
        f"Consider the pytest test class `{TEST_FILE}::{TEST_CLASS}` "
        f"(class `{TEST_CLASS}` in `{TEST_FILE}`). The answer aggregates behavior "
        f"across ALL test methods in that class, executed in pytest default "
        f"collection order (alphabetical by test method name). The covered "
        f"pytest ids are: {method_list}. "
        f"During that combined run, the function `{TARGET_FUNC}` in "
        f"`{TARGET_FILE}` is reached only indirectly: each test constructs "
        f"composite loaders and calls their `load` method (for example "
        f"`ChoiceLoader.load` or `PrefixLoader.load`), which in turn calls "
        f"`PackageLoader.load` and thereby enters `{TARGET_FUNC}`; the tests "
        f"never call `{TARGET_FUNC}` directly. "
        f"Report per-type exception observation counts for `{TARGET_FUNC}` "
        f"across the entire combined run. An observation is one moment during "
        f"execution of `{TARGET_FUNC}` when Python unwinds an exception into "
        f"that exact frame: either because code in that frame raised it, or "
        f"because an exception propagated up from a callee before being handled "
        f"in a different frame. Do not count exceptions that are raised and "
        f"fully handled inside a callee without ever reaching `{TARGET_FUNC}`. "
        f"Each such delivery counts once; re-raising the same exception object "
        f"in the same frame would count again, but that does not occur in this "
        f"target during these tests. "
        f"Exception type naming uses bare `type(exc).__name__` for built-in "
        f"exceptions (for example `ValueError`, never `builtins.ValueError`) "
        f"and `module.QualName` for all others (for example "
        f"`haystack.core.errors.PipelineError`). "
        f"Counts are totals over all invocations and all test methods in the "
        f"class (the same type observed in five separate invocations "
        f"contributes five to its count). "
        f"Return a JSON object with exactly one key, `exception_type_counts`, "
        f"whose value is a JSON array of objects. Each object must contain "
        f"exactly two keys: `exception_type` (string) and `count` (JSON "
        f"integer). Include one object for every exception type observed at "
        f"least once. Sort the array ascending by `exception_type` using ASCII "
        f"order."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    testcase_path = Path(__file__).resolve().parent / "testcase.py"
    test_method_ids = _discover_test_method_ids(testcase_path)
    events = _load_target_events(args.trace_log)
    exception_type_counts = _exception_type_counts(events)

    oracle_answer = {"exception_type_counts": exception_type_counts}
    payload = {
        "question_kind": "M5_Exceptions",
        "question": _build_question(test_method_ids),
        "template_answer": {
            "exception_type_counts": [{"count": "int", "exception_type": "str"}]
        },
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
