#!/usr/bin/env python3
"""Parse trace log for M1_IntraProceduralCFG line_execution_counts oracle."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/logging.py"
TARGET_FUNC = "rich.logging.RichHandler.emit"
TARGET_FUNC_SUFFIX = "RichHandler.emit"
TEST_FILE = "rich_qa/logging_emit_m1_cfg/files/testcase.py"
TEST_CLASS = "TestRichHandlerEmitFlow"

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>[^:]+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)

QUESTION = (
    f"Consider pytest tests in `{TEST_FILE}::{TEST_CLASS}` (all `test_*` methods "
    "in that class, executed in pytest's default collection order). The answer "
    "aggregates behavior across every test method in the class during one full "
    "pytest run of the class.\n\n"
    f"Target function: `{TARGET_FUNC}` in `{TARGET_FILE}` (the method body spans "
    "lines 140-188 as checked into the repository).\n\n"
    "Scope: every physical source line from 140 through 188 inclusive in "
    f"`{TARGET_FILE}`. Blank lines and comment-only lines inside that range are "
    "included in scope and must appear in the output; if they never receive a "
    "`line` trace event, report `count: 0`. The `def` line (138), decorator "
    "lines, and docstring line (139) are outside scope.\n\n"
    "Executed line definition: count only trace events with `event=line` whose "
    f"qualname equals `{TARGET_FUNC}` and whose normalized file path ends with "
    f"`{TARGET_FILE}`. Exclude `call`, `return`, and `exception` events. Each "
    "counted event contributes to the total for its reported 1-based physical "
    "line number in the source file (the same numbering `sys.settrace` uses). "
    "For multi-line statements (for example the `if` spanning lines 142-146), "
    "the `line` event fires on the physical line where execution resumes for "
    "that statement; count events on the line number reported in the trace, "
    "not on continuation lines that share the same logical statement unless "
    "execution actually visits them.\n\n"
    "Counting: for each line L in scope, `count` is the total number of `line` "
    "events at line L summed across all invocations of the target during the "
    "entire test run (all test methods combined). Each separate `emit` call is "
    "one invocation; lines inside branches execute only when that branch is "
    "taken, and repeated invocations accumulate.\n\n"
    "Return JSON with top-level key `line_execution_counts`: a list of objects "
    "each having keys `line` (int, 1-based source line number) and `count` "
    "(int, non-negative). Include every line in scope even when `count` is 0. "
    "Sort the list by `line` ascending; when lines differ, smaller line numbers "
    "come first."
)


def _func_matches(func: str) -> bool:
    return func == TARGET_FUNC or func.endswith(TARGET_FUNC_SUFFIX)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.find(TARGET_FILE)
    if idx == -1:
        return normalized
    return normalized[idx:]


def _body_line_range(repo_root: Path) -> range:
    source = (repo_root / TARGET_FILE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RichHandler":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "emit":
                    body = list(item.body)
                    if (
                        body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(getattr(body[0].value, "value", None), str)
                    ):
                        body = body[1:]
                    if not body:
                        raise SystemExit("Target function has empty body")
                    start = body[0].lineno
                    end = max(
                        stmt.end_lineno
                        if getattr(stmt, "end_lineno", None)
                        else stmt.lineno
                        for stmt in body
                    )
                    return range(start, end + 1)
    raise SystemExit(f"Could not locate RichHandler.emit in {TARGET_FILE}")


def _parse_trace(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log empty: {path}")

    events: list[dict] = []
    for raw in text.splitlines():
        m = TRACE_RE.match(raw)
        if not m:
            continue
        file_path = _normalize_file(m.group("file"))
        if file_path != TARGET_FILE:
            continue
        func = m.group("func")
        if not _func_matches(func):
            continue
        events.append(
            {
                "lineno": int(m.group("lineno")),
                "func": func,
                "event": m.group("event"),
            }
        )
    return events


def _line_execution_counts(events: list[dict], scope: range) -> list[dict]:
    counts = {line: 0 for line in scope}
    line_events = 0
    for ev in events:
        if ev["event"] != "line":
            continue
        line_events += 1
        lineno = ev["lineno"]
        if lineno in counts:
            counts[lineno] += 1
    if line_events == 0:
        raise SystemExit(f"No line events for {TARGET_FUNC} in trace log")
    return [{"line": line, "count": counts[line]} for line in sorted(counts)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default="/testbed")
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    scope = _body_line_range(repo_root)
    events = _parse_trace(Path(args.trace_log))
    if not events:
        raise SystemExit(f"No trace events for {TARGET_FUNC} in {args.trace_log}")

    line_counts = _line_execution_counts(events, scope)
    oracle_answer = {"line_execution_counts": line_counts}
    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle_answer, sort_keys=True))


if __name__ == "__main__":
    main()
