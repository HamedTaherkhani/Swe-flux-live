#!/usr/bin/env python3
"""Parse trace logs for sandbox_getitem_m6_calls (M6_InterProceduralCFG)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "src/jinja2/sandbox.py"
TARGET_FUNC = "jinja2.sandbox.SandboxedEnvironment.getitem"
TARGET_MODULE = "jinja2.sandbox"

TEST_CLASS = "SandboxGetitemM6CallsTest"
TEST_FILE = "jinja_qa/sandbox_getitem_m6_calls/files/testcase.py"

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
)


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    if TARGET_FILE in normalized:
        return TARGET_FILE
    return normalized


def _discover_scope_functions(source_path: Path) -> list[tuple[str, str]]:
    """Return sorted (repo_file, dotted_qualname) for in-scope functions."""
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    entries: list[tuple[str, str]] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            entries.append(
                (TARGET_FILE, f"{TARGET_MODULE}.{node.name}")
            )
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entries.append(
                        (
                            TARGET_FILE,
                            f"{TARGET_MODULE}.{node.name}.{item.name}",
                        )
                    )

    entries.sort(key=lambda pair: pair[1])
    return entries


def _parse_trace_line(raw_line: str) -> dict[str, str | int] | None:
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
    }


def _load_trace_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is not None:
            events.append(parsed)

    if not events:
        _fail(f"trace log contains no parseable events: {trace_log}")
    return events


def _count_invocations(
    events: list[dict[str, str | int]],
    scope: list[tuple[str, str]],
) -> list[dict[str, str | int]]:
    scope_set = set(scope)
    counts = {qualname: 0 for _, qualname in scope}

    for event in events:
        if event["event"] != "call":
            continue
        file_key = str(event["file"])
        func_key = str(event["func"])
        if (file_key, func_key) in scope_set:
            counts[func_key] += 1

    return [
        {"file": file_path, "func": qualname, "count": counts[qualname]}
        for file_path, qualname in scope
    ]


def _count_target_activity(events: list[dict[str, str | int]]) -> tuple[int, int, int, int]:
    line_events = 0
    distinct_lines: set[int] = set()
    call_events = 0
    traced_call_events = 0
    traced_funcs: set[str] = set()

    for event in events:
        if event["file"] != TARGET_FILE:
            continue
        if event["event"] == "call":
            traced_call_events += 1
            traced_funcs.add(str(event["func"]))
        if event["func"] != TARGET_FUNC:
            continue
        if event["event"] == "line":
            line_events += 1
            distinct_lines.add(int(event["lineno"]))
        elif event["event"] == "call":
            call_events += 1

    return line_events, len(distinct_lines), call_events, len(traced_funcs)


def _build_question() -> str:
    return (
        "Consider the pytest test class "
        f"`{TEST_FILE}::{TEST_CLASS}` (class `{TEST_CLASS}` in "
        f"`{TEST_FILE}`). The answer aggregates invocation counts across "
        "**all** test methods in that class (`def test_...`), in the order "
        "pytest discovers them (definition order in the class body). "
        "During that combined run, track every function and method **defined** "
        f"in `{TARGET_FILE}`: all module-level functions and all methods of "
        "every class defined in that file. Exclude nested functions and "
        "closures (for example the inner function created inside "
        "`SandboxedEnvironment.wrap_str_format`), class properties, "
        "comprehensions, lambdas, and methods inherited from parent classes "
        "but not redefined in this file. Include `__init__` and other dunder "
        "methods when they appear as a `def` in this file. "
        "Function identity uses the dotted qualname format `module.function` "
        "or `module.Class.method` (for example "
        "`jinja2.sandbox.SandboxedEnvironment.getitem`). "
        "One invocation is one Python `call` trace event for that function's "
        "frame, whether the call is direct, nested, recursive, or made from "
        "any other frame. Generator or coroutine resumption does **not** emit "
        "another `call` event and therefore does not increment the count. "
        "Functions in scope that never execute during the aggregated run "
        "appear with `count: 0`. "
        "The primary target of this scenario is "
        f"`{TARGET_FUNC}` in `{TARGET_FILE}`; your counts must reflect every "
        "in-scope function in that file. "
        "Report the answer as a JSON object with exactly one key, "
        "`invocation_counts`, whose value is a JSON array of objects each "
        "having keys `file` (repo-relative path string, e.g. "
        f"`{TARGET_FILE}`), `func` (dotted qualname string), and `count` "
        "(non-negative integer). Sort the array by `func` ascending; when "
        "two entries would share the same `func` (they should not), break ties "
        "by `file` ascending."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    scope = _discover_scope_functions(_repo_root() / TARGET_FILE)
    if not scope:
        _fail(f"no in-scope functions discovered in {TARGET_FILE}")

    events = _load_trace_events(args.trace_log)

    target_line_events, distinct_lines, target_calls, traced_func_count = (
        _count_target_activity(events)
    )
    if target_calls == 0:
        _fail(f"trace log contains zero call events for {TARGET_FUNC}")
    if target_line_events < 50:
        _fail(
            f"only {target_line_events} line events for {TARGET_FUNC}; "
            "need at least 50"
        )
    if distinct_lines < 8:
        _fail(
            f"only {distinct_lines} distinct executed lines for {TARGET_FUNC}; "
            "need at least 8"
        )
    if target_calls < 15:
        _fail(
            f"only {target_calls} call events for {TARGET_FUNC}; need at least 15"
        )
    if traced_func_count < 4:
        _fail(
            f"only {traced_func_count} distinct traced functions called; "
            "need at least 4"
        )

    invocation_counts = _count_invocations(events, scope)
    oracle_answer = {"invocation_counts": invocation_counts}
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": _build_question(),
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
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
