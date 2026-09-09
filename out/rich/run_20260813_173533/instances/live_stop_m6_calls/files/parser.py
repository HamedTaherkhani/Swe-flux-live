#!/usr/bin/env python3
"""Parse trace log for M6 invocation counts over Live class methods."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

TARGET_FILE = "rich/live.py"
TARGET_CLASS = "Live"
TARGET_FUNC = "rich.live.Live.stop"
TEST_CLASS = "TestLiveStopInvocationCounts"
TEST_FILE = "rich_qa/live_stop_m6_calls/files/testcase.py"

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
    f"Scope: every function and method defined directly in class `{TARGET_CLASS}` "
    f"in `{TARGET_FILE}` — all instance methods, dunder methods such as "
    "`__init__`, `__enter__`, and `__exit__`, and `@property` getter functions "
    "implemented in that class body. Exclude nested functions and closures inside "
    "method bodies, inline comprehensions as separate scopes, inherited methods "
    "not defined in this file, module-level code (including the "
    "`if __name__ == \"__main__\"` block), and methods of other classes defined "
    "in the same file (such as `_RefreshThread`).\n\n"
    "Function identity: dotted qualname `module.Class.method`, for example "
    "`rich.console.Console.print` — for this scope, entries look like "
    f"`rich.live.{TARGET_CLASS}.stop`.\n\n"
    "Invocation counting: one invocation is one Python `call` trace event for "
    "that function's frame during the aggregated test run, including calls made "
    "directly, transitively, recursively, or from any other frame. If a "
    "generator or coroutine suspension/resumption emits another distinct `call` "
    "event for the same qualname, that resumption counts as an additional "
    "invocation.\n\n"
    "Zero rule: every in-scope function appears exactly once; functions that "
    "never execute have `count: 0`.\n\n"
    "Report `invocation_counts`: a JSON list of objects "
    '`{"file": "<repo-relative path>", "func": "<qualname>", "count": <int>}`. '
    f"For this scope, `file` is always `{TARGET_FILE}`. Sort the list by `func` "
    "ascending (Unicode code-point order). If two entries could share the same "
    "`func` string, break ties by `file` ascending."
)


def _discover_scope_functions(repo_root: Path) -> list[str]:
    source = (repo_root / TARGET_FILE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    qualnames: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualnames.append(f"rich.live.{TARGET_CLASS}.{item.name}")
            break
    else:
        raise SystemExit(f"Class {TARGET_CLASS} not found in {TARGET_FILE}")
    if not qualnames:
        raise SystemExit(f"No methods found on class {TARGET_CLASS}")
    return sorted(qualnames)


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.find(TARGET_FILE)
    if idx >= 0:
        return TARGET_FILE
    return normalized


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
        file_norm = _normalize_file(m.group("file"))
        if file_norm != TARGET_FILE:
            continue
        events.append(
            {
                "file": file_norm,
                "func": m.group("func"),
                "event": m.group("event"),
            }
        )
    return events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo-root", default="/testbed")
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    scope_funcs = _discover_scope_functions(repo_root)
    events = _parse_trace(Path(args.trace_log))

    call_counts = {func: 0 for func in scope_funcs}
    target_calls = 0
    for ev in events:
        if ev["event"] != "call":
            continue
        func = ev["func"]
        if func in call_counts:
            call_counts[func] += 1
        if func == TARGET_FUNC:
            target_calls += 1

    if target_calls == 0:
        raise SystemExit(
            f"No call events for target function {TARGET_FUNC} in {args.trace_log}"
        )

    invocation_counts = [
        {"file": TARGET_FILE, "func": func, "count": call_counts[func]}
        for func in scope_funcs
    ]

    oracle_answer = {"invocation_counts": invocation_counts}
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
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
