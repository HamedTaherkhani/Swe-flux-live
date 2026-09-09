#!/usr/bin/env python3
"""Parse trace log into oracle.json for runtime_new_context_m4_dataflow."""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/runtime.py"
TARGET_FUNC = "jinja2.runtime.new_context"

TRACKED_VARIABLES = (
    "environment",
    "template_name",
    "blocks",
    "vars",
    "shared",
    "globals",
    "locals",
    "parent",
    "key",
    "value",
)

QUESTION = """\
During the pytest run for test class \
`jinja_qa/runtime_new_context_m4_dataflow/files/testcase.py::TestNewContextDataFlowIndirect`, \
report **all observed def-use pairs** for the target function with per-pair observation \
counts. The answer aggregates behavior across **every** `test_*` method in that class; \
methods are identified by pytest node ids and executed in unittest discovery order \
(ascending ASCII by method name).

The target is `jinja2.runtime.new_context` defined in `src/jinja2/runtime.py` (the \
`def new_context` line is line 93 in that file as checked into this repository). \
Tests reach it **indirectly** through Jinja template rendering: `pass_context` filters \
invoke `Context.call`, which may call `Context.derived`, which calls `new_context`. \
Some tests also call `spawn_derived`, a `pass_context` filter that calls `ctx.derived` \
with programmatic locals. No test imports or calls `new_context` directly.

**Tracked variables** (only these ten names; ignore any other locals):

`environment`, `template_name`, `blocks`, `vars`, `shared`, `globals`, `locals`, \
`parent`, `key`, `value`

**Def and use rules** (line numbers are absolute, 1-based, in `src/jinja2/runtime.py`; \
the executed-line trace event fires on the line where the statement begins):

- Parameters (`environment`, `template_name`, `blocks`, `vars`, `shared`, `globals`, \
`locals`) are **defined** at line 93 on each invocation's `call` event (the `def` line).
- A simple assignment `name = expr` **uses** every variable referenced in `expr` on that \
line, then **defines** `name` on that line (for example `vars = {}` at line 104 defines \
`vars` after any uses on that line).
- `for key, value in locals.items()` at line 114 **defines** `key` and `value` on line 114 \
and **uses** `locals` on line 114.
- `parent[key] = value` at line 116 **uses** `parent`, `key`, and `value` on line 116; \
it does **not** define `parent` (the binding is unchanged).
- `if` and `while` tests **use** referenced variables on the test's line.
- `return environment.context_class(...)` at line 117 **uses** `environment`, `parent`, \
`template_name`, `blocks`, and `globals` on line 117 (each AST load counts separately, so \
`environment` may contribute multiple observations on that line).
- There are no augmented assignments in this function; the augmented-assignment rule does \
not apply.

**Observation:** one executed `line` event at `use_line` where a tracked variable is \
**used** as above, attributed to the **reaching definition** — the `def_line` of the \
definition that most recently bound that variable in the same invocation before this \
use (parameters reach from line 93 until reassigned). Uses inside a loop body count once \
per iteration. After a variable is defined on a line, that definition is in effect for \
subsequent lines in the same invocation (including later loop iterations unless \
redefined).

**Invocation scope:** only trace events whose qualified name is exactly \
`jinja2.runtime.new_context` and whose file path ends with `src/jinja2/runtime.py` belong \
to the target. Process events chronologically; each `call` at line 93 starts a fresh \
reaching-def state for that invocation. Ignore events from other functions.

**Counts:** for each triple `(variable, def_line, use_line)` that occurs at least once, \
`count` is the total number of observations summed across **all** invocations in **all** \
test methods in the class. Pairs that never occur are omitted.

**Output:** JSON with top-level key `observed_def_use_pairs`: a list of objects \
`{variable, def_line, use_line, count}`. Sort the list by `variable` ascending (bytewise \
ASCII / `strcmp` order), then `def_line` ascending, then `use_line` ascending. The triple \
`(variable, def_line, use_line)` is unique; multiplicity lives only in `count` (no \
duplicate rows).\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _build_line_effects(repo_root: Path) -> tuple[int, dict[int, list[str]], dict[int, list[str]]]:
    source_path = repo_root / TARGET_REL_FILE
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "new_context"
    )
    def_line = func.lineno
    tracked = frozenset(TRACKED_VARIABLES)
    line_uses: dict[int, list[str]] = defaultdict(list)
    line_defs: dict[int, list[str]] = defaultdict(list)

    def add_use(var: str, line: int) -> None:
        if var in tracked:
            line_uses[line].append(var)

    def add_def(var: str, line: int) -> None:
        if var in tracked:
            line_defs[line].append(var)

    def collect_uses(node: ast.AST, line: int) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                add_use(child.id, line)

    def visit_stmt(stmt: ast.AST) -> None:
        if isinstance(stmt, ast.If):
            collect_uses(stmt.test, stmt.lineno)
            for child in stmt.body:
                visit_stmt(child)
            for child in stmt.orelse:
                visit_stmt(child)
        elif isinstance(stmt, ast.For):
            add_def("key", stmt.lineno)
            add_def("value", stmt.lineno)
            collect_uses(stmt.iter, stmt.lineno)
            for child in stmt.body:
                visit_stmt(child)
            for child in stmt.orelse:
                visit_stmt(child)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    collect_uses(stmt.value, stmt.lineno)
                    add_def(target.id, stmt.lineno)
                elif isinstance(target, ast.Subscript):
                    collect_uses(target.value, stmt.lineno)
                    collect_uses(target.slice, stmt.lineno)
                    collect_uses(stmt.value, stmt.lineno)
                else:
                    collect_uses(stmt.value, stmt.lineno)
        elif isinstance(stmt, ast.Return):
            collect_uses(stmt.value, stmt.lineno)
        elif isinstance(stmt, ast.AugAssign):
            collect_uses(stmt.target, stmt.lineno)
            collect_uses(stmt.value, stmt.lineno)
            if isinstance(stmt.target, ast.Name):
                add_def(stmt.target.id, stmt.lineno)

    for arg in func.args.args + func.args.posonlyargs + func.args.kwonlyargs:
        add_def(arg.arg, def_line)
    if func.args.vararg:
        add_def(func.args.vararg.arg, def_line)
    if func.args.kwarg:
        add_def(func.args.kwarg.arg, def_line)

    for stmt in func.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        visit_stmt(stmt)

    return def_line, dict(line_uses), dict(line_defs)


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
                match.group("file").replace("\\", "/"),
            )
        )

    if not events:
        raise SystemExit(f"ERROR: no parseable trace events in: {trace_log}")

    return events


def _is_target_event(func: str, file_path: str) -> bool:
    return func == TARGET_FUNC and file_path.endswith(TARGET_REL_FILE)


def _compute_pairs(
    events: list[tuple[str, str, int, str]],
    def_line: int,
    line_uses: dict[int, list[str]],
    line_defs: dict[int, list[str]],
) -> list[dict[str, int | str]]:
    target_events = [
        event
        for event in events
        if _is_target_event(event[1], event[3])
        and event[0] in {"call", "line", "return", "exception"}
    ]
    if not target_events:
        raise SystemExit(f"ERROR: zero trace events for target function {TARGET_FUNC}")

    pair_counts: dict[tuple[str, int, int], int] = defaultdict(int)
    current_defs: dict[str, int] = {}
    active = False

    for event, _func, lineno, _file in events:
        if not _is_target_event(_func, _file):
            continue

        if event == "call" and lineno == def_line:
            current_defs = {var: def_line for var in TRACKED_VARIABLES}
            active = True
            continue

        if not active:
            continue

        if event == "line":
            for var in line_uses.get(lineno, []):
                if var not in current_defs:
                    raise SystemExit(
                        f"ERROR: use of {var!r} at line {lineno} without reaching def"
                    )
                pair_counts[(var, current_defs[var], lineno)] += 1
            for var in line_defs.get(lineno, []):
                current_defs[var] = lineno
        elif event in {"return", "exception"}:
            active = False
            current_defs = {}

    if not pair_counts:
        raise SystemExit("ERROR: no def-use observations recorded for target function")

    pairs = [
        {
            "variable": variable,
            "def_line": def_line_num,
            "use_line": use_line,
            "count": count,
        }
        for (variable, def_line_num, use_line), count in sorted(
            pair_counts.items(),
            key=lambda item: (item[0][0], item[0][1], item[0][2]),
        )
    ]
    return pairs


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

    def_line, line_uses, line_defs = _build_line_effects(args.repo_root)
    events = _parse_trace_events(args.trace_log)
    answer = _compute_pairs(events, def_line, line_uses, line_defs)

    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {
                    "count": "int",
                    "def_line": "int",
                    "use_line": "int",
                    "variable": "str",
                }
            ],
        },
        "oracle_answer": {
            "observed_def_use_pairs": answer,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote oracle with {len(answer)} def-use pairs to {args.out}")


if __name__ == "__main__":
    main()
