#!/usr/bin/env python3
"""Parse trace log into oracle.json for visitor_visit_m6_calls."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/visitor.py"
TARGET_FUNC = "jinja2.visitor.NodeVisitor.visit"

QUESTION = """\
During the pytest run for test class \
`jinja_qa/visitor_visit_m6_calls/files/testcase.py::TestVisitInvocationCounts`, \
report **invocation counts** aggregated across **all** `test_*` methods in that class. \
Methods are identified by their pytest node ids and are ordered chronologically as pytest \
executes them (unittest discovery order: ascending ASCII by method name). Counts from \
every test method are **summed**; do not report per-method totals.

The primary target function is `jinja2.visitor.NodeVisitor.visit` defined in \
`src/jinja2/visitor.py` (the `def visit` line is line 35 in that file). Each test \
method calls `visit` directly on a `NodeVisitor` or `NodeTransformer` instance.

**Scope:** consider every function and method **defined** in `src/jinja2/visitor.py`. \
This includes all methods of classes `NodeVisitor` and `NodeTransformer` that appear in \
that file. Exclude nested functions, closures, comprehension frames, properties, \
`__init__`, dunder methods, and methods inherited from other modules but not redefined \
in this file. There are no module-level functions in this file.

**Function identity:** use the dotted qualname traced by Python as \
`module.Class.method`, for example `jinja2.visitor.NodeVisitor.get_visitor`. The `file` \
field is always the repo-relative path `src/jinja2/visitor.py`.

**What counts as one invocation:** one Python `call` trace event whose qualified name \
matches an in-scope function defined in `src/jinja2/visitor.py`. Count every such `call` \
during the pytest run, including calls made recursively, transitively, or from any caller \
frame. A generator or coroutine resumption does **not** emit another `call` event for the \
same frame and therefore does **not** increment the count again.

**Zero rule:** every in-scope function defined in `src/jinja2/visitor.py` must appear in \
the answer. Functions that never execute during the aggregated run have `count: 0`.

**Sort order:** sort the `invocation_counts` list by the `func` field in ascending ASCII \
order (bytewise / `strcmp` order). The `file` field is identical for every entry; when \
`func` values tie (they cannot), break ties by `file` ascending ASCII.

Return JSON with top-level key `invocation_counts` whose value is a list of objects, each \
with exactly these keys:

- `file`: repo-relative path (`str`), always `src/jinja2/visitor.py`
- `func`: fully qualified name (`str`) as described above
- `count`: non-negative integer (`int`), total `call` events for that function\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _repo_relative_path(abs_path: str) -> str:
    normalized = abs_path.replace("\\", "/")
    marker = f"/{TARGET_REL_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        return normalized.lstrip("/")
    return normalized[idx + 1 :]


def _enumerate_scope_functions(repo_root: Path) -> list[str]:
    source_path = repo_root / TARGET_REL_FILE
    if not source_path.is_file():
        raise SystemExit(f"ERROR: target source not found: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    module_name = "jinja2.visitor"
    names: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in {"NodeVisitor", "NodeTransformer"}:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.append(f"{module_name}.{node.name}.{item.name}")

    if not names:
        raise SystemExit("ERROR: no in-scope functions discovered via AST")

    return sorted(names)


def _parse_trace_events(trace_log: Path) -> list[tuple[str, str, int, str]]:
    if not trace_log.is_file():
        raise SystemExit(f"ERROR: trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_log}")

    events: list[tuple[str, str, int, str]] = []
    for line in text.splitlines():
        match = EVENT_RE.search(line)
        if match is None:
            continue
        events.append(
            (
                match.group("event"),
                match.group("func"),
                int(match.group("line")),
                _repo_relative_path(match.group("file")),
            )
        )

    if not events:
        raise SystemExit(f"ERROR: no parseable trace events in: {trace_log}")

    return events


def _compute_invocation_counts(
    events: list[tuple[str, str, int, str]],
    scope_funcs: list[str],
) -> list[dict[str, int | str]]:
    target_events = [
        e
        for e in events
        if e[1] == TARGET_FUNC and e[0] in {"call", "line", "return", "exception"}
    ]
    if not target_events:
        raise SystemExit(
            f"ERROR: zero trace events for target function {TARGET_FUNC}"
        )

    visit_calls = [e for e in events if e[0] == "call" and e[1] == TARGET_FUNC]
    if not visit_calls:
        raise SystemExit(
            f"ERROR: zero call events for target function {TARGET_FUNC}"
        )

    counts = {name: 0 for name in scope_funcs}
    scope_set = set(scope_funcs)

    for event, func, _lineno, rel_file in events:
        if event != "call":
            continue
        if func not in scope_set:
            continue
        if rel_file != TARGET_REL_FILE:
            continue
        counts[func] += 1

    answer = [
        {
            "file": TARGET_REL_FILE,
            "func": func,
            "count": counts[func],
        }
        for func in sorted(scope_funcs)
    ]

    if all(entry["count"] == 0 for entry in answer):
        raise SystemExit("ERROR: all invocation counts are zero")

    return answer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args()

    scope_funcs = _enumerate_scope_functions(args.repo_root)
    events = _parse_trace_events(args.trace_log)
    answer = _compute_invocation_counts(events, scope_funcs)

    oracle = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}],
        },
        "oracle_answer": {
            "invocation_counts": answer,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote oracle with {len(answer)} invocation count entries to {args.out}")


if __name__ == "__main__":
    main()
