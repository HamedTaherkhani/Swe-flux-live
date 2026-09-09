#!/usr/bin/env python3
"""Parse trace log and emit oracle.json for syntax_get_syntax_s4_dataflow."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

TARGET_FILE = "rich/syntax.py"
TARGET_FUNC = "rich.syntax.Syntax._get_syntax"
DEF_LINE = 652
TRACKED_VARIABLES = (
    "code_width",
    "line_no",
    "line_offset",
    "lines",
    "numbers_column_width",
    "render_options",
    "transparent_background",
    "wrapped_lines",
)

_EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _parse_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.is_file():
        raise SystemExit(f"Trace log not found: {trace_path}")

    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise SystemExit(f"Trace log is empty: {trace_path}")

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        match = _EVENT_RE.search(line)
        if not match:
            continue
        file_path = match.group("file").replace("\\", "/")
        if TARGET_FILE not in file_path:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        events.append(
            {
                "lineno": int(match.group("lineno")),
                "event": match.group("event"),
            }
        )

    if not events:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )
    return events


def _invocation_line_events(events: list[dict[str, Any]]) -> list[int]:
    invocation: list[int] = []
    in_call = False
    for event in events:
        kind = event["event"]
        if kind == "call":
            if in_call:
                raise SystemExit("Multiple calls to target without return")
            in_call = True
            continue
        if not in_call:
            continue
        if kind == "line":
            invocation.append(event["lineno"])
        elif kind == "return":
            break
    if not invocation:
        raise SystemExit("No line events recorded for target invocation")
    return invocation


class _DefUseCollector(ast.NodeVisitor):
    """Collect def/use events per source line in evaluation order."""

    def __init__(self, tracked: set[str]) -> None:
        self.tracked = tracked
        self.events: dict[int, list[tuple[str, str]]] = {}

    def _emit(self, lineno: int, name: str, kind: str) -> None:
        if name in self.tracked:
            self.events.setdefault(lineno, []).append((name, kind))

    def _visit_expr_for_loads(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                self._emit(child.lineno, child.id, "use")

    def _visit_target_for_stores(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            self._emit(node.lineno, node.id, "def")
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self._visit_target_for_stores(element)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._visit_expr_for_loads(node.value)
        for target in node.targets:
            self._visit_target_for_stores(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._visit_expr_for_loads(node.value)
        if node.target is not None:
            self._visit_target_for_stores(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._emit(node.target.lineno, node.target.id, "use")
        self._visit_expr_for_loads(node.value)
        self._visit_target_for_stores(node.target)

    def visit_For(self, node: ast.For) -> None:
        self._visit_expr_for_loads(node.iter)
        self._visit_target_for_stores(node.target)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_While(self, node: ast.While) -> None:
        self._visit_expr_for_loads(node.test)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_If(self, node: ast.If) -> None:
        self._visit_expr_for_loads(node.test)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None:
            self._visit_expr_for_loads(node.value)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._visit_expr_for_loads(node.value)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self._visit_expr_for_loads(item.context_expr)
            if item.optional_vars is not None:
                self._visit_target_for_stores(item.optional_vars)
        for child in node.body:
            self.visit(child)

    def visit_Try(self, node: ast.Try) -> None:
        for child in node.body:
            self.visit(child)
        for handler in node.handlers:
            if handler.type is not None:
                self._visit_expr_for_loads(handler.type)
            if handler.name is not None:
                self._emit(handler.name.lineno, handler.name, "def")
            for child in handler.body:
                self.visit(child)
        for child in node.orelse:
            self.visit(child)
        for child in node.finalbody:
            self.visit(child)

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is not None:
            self._visit_expr_for_loads(node.exc)
        if node.cause is not None:
            self._visit_expr_for_loads(node.cause)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._visit_expr_for_loads(node.test)
        if node.msg is not None:
            self._visit_expr_for_loads(node.msg)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._visit_expr_for_loads(target)


def _function_node(source_path: Path) -> ast.FunctionDef:
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "Syntax":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "_get_syntax":
                    return child
    raise SystemExit(f"Could not locate {TARGET_FUNC} in {source_path}")


def _line_events_for_function(
    func_node: ast.FunctionDef, tracked: Iterable[str]
) -> dict[int, list[tuple[str, str]]]:
    tracked_set = set(tracked)
    collector = _DefUseCollector(tracked_set)
    for stmt in func_node.body:
        collector.visit(stmt)
    return collector.events


def _observed_def_use_pairs(
    executed_lines: list[int],
    line_events: dict[int, list[tuple[str, str]]],
    tracked: Iterable[str],
) -> list[dict[str, int | str]]:
    tracked_set = set(tracked)
    current_def: dict[str, int] = {name: DEF_LINE for name in tracked_set}
    pairs: set[tuple[str, int, int]] = set()

    for lineno in executed_lines:
        for name, kind in line_events.get(lineno, []):
            if kind == "use":
                pairs.add((name, current_def[name], lineno))
            elif kind == "def":
                current_def[name] = lineno

    ordered = sorted(
        (
            {"variable": name, "def_line": def_line, "use_line": use_line}
            for name, def_line, use_line in pairs
        ),
        key=lambda item: (item["variable"], item["def_line"], item["use_line"]),
    )
    return ordered


def _build_question() -> str:
    var_list = ", ".join(f"`{name}`" for name in TRACKED_VARIABLES)
    return (
        "Category S4_DataFlow (observed def-use pairs).\n"
        "\n"
        "Test scope: pytest id "
        "`rich_qa/syntax_get_syntax_s4_dataflow/files/testcase.py::"
        "TestSyntaxGetSyntaxDataFlow::test_get_syntax_line_number_wrap_slice` — "
        "the answer covers exactly that single test method's one execution.\n"
        "\n"
        "Target: `rich.syntax.Syntax._get_syntax` in repo-relative file "
        "`rich/syntax.py` (function header begins at line 652).\n"
        "\n"
        "Invocation: there is exactly one call to the target during the test run. "
        "All analysis is for that invocation's frame only.\n"
        "\n"
        "Executed lines: process every `line` event delivered by CPython "
        "`sys.settrace` while `rich.syntax.Syntax._get_syntax` is on the call "
        "stack (from function entry until return), in chronological order. "
        "Repeat the same source line number each time it appears (for example "
        "inside loops). Line numbers are absolute 1-based line numbers in the "
        "repository file `rich/syntax.py`; for a multi-line statement, the "
        "reported line is where that statement begins.\n"
        "\n"
        "Tracked variables: "
        f"{var_list}.\n"
        "\n"
        "Definitions: a variable is *defined* on a line when it is bound by "
        "function parameters, plain assignment (`x = ...`), annotated assignment, "
        "augmented assignment (`x += 1` counts as a new definition on that line "
        "after the read of the prior value), `for` loop targets (`for x in ...` "
        "defines `x` on the `for` header line each iteration), `with ... as x`, "
        "or exception-handler `as` bindings. Function parameters "
        "`console` and `options` are not tracked; every tracked name that is a "
        "parameter would still be defined at line 652, but only the listed names "
        "are reported. Comprehension-local variables and `except` names outside "
        "the tracked set are ignored.\n"
        "\n"
        "Uses: a variable is *used* on a line when it is read (including as part "
        "of an expression, subscript, attribute base, or call argument) before any "
        "new definition of that name on the same line. For augmented assignment, "
        "the pre-update read is a use on that line and the write is a separate "
        "definition on the same line after the use.\n"
        "\n"
        "Def-use pair: for each tracked variable `v`, each use of `v` on executed "
        "line `U` pairs with the most recent definition line `D` of `v` that "
        "executed before that use and was not superseded by a later definition "
        "of `v` between `D` and `U` (inclusive of `D`, exclusive of redefinition "
        "between). Formally: walk executed lines in order; maintain the current "
        "definition line per tracked variable; on each use, record "
        "`{variable: v, def_line: D, use_line: U}`; on each definition, update "
        "the current definition line for `v` to that line. Parameters count as "
        "defined at line 652 only for tracked names that appear in the signature "
        "(none of the tracked names are parameters here).\n"
        "\n"
        "Deduplication: if the same triple `(variable, def_line, use_line)` arises "
        "multiple times (for example from repeated loop iterations), include it "
        "once.\n"
        "\n"
        "Sort order: ascending by `variable` (lexicographic), then `def_line`, "
        "then `use_line`.\n"
        "\n"
        "Question: During the test run, what are all unique observed def-use pairs "
        "for the tracked variables listed above in `rich.syntax.Syntax._get_syntax`?\n"
        "\n"
        "Answer format: a JSON object with exactly one key `observed_def_use_pairs` "
        "whose value is a JSON array of objects, each with exactly three keys: "
        "`variable` (string), `def_line` (integer), `use_line` (integer)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    events = _parse_trace_events(Path(args.trace_log))
    executed_lines = _invocation_line_events(events)
    line_events = _line_events_for_function(
        _function_node(_repo_root() / TARGET_FILE), TRACKED_VARIABLES
    )
    pairs = _observed_def_use_pairs(executed_lines, line_events, TRACKED_VARIABLES)

    if len(pairs) < 8:
        raise SystemExit(f"Expected at least 8 def-use pairs, found {len(pairs)}")

    line_event_count = sum(1 for event in events if event["event"] == "line")
    distinct_lines = len({event["lineno"] for event in events if event["event"] == "line"})
    if line_event_count < 40:
        raise SystemExit(
            f"Expected at least 40 line events, found {line_event_count}"
        )
    if distinct_lines < 8:
        raise SystemExit(
            f"Expected at least 8 distinct executed lines, found {distinct_lines}"
        )

    oracle_answer = {"observed_def_use_pairs": pairs}
    template_answer = {
        "observed_def_use_pairs": [
            {"variable": "str", "def_line": "int", "use_line": "int"}
        ]
    }
    payload = {
        "question_kind": "S4_DataFlow",
        "question": _build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
