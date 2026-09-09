#!/usr/bin/env python3
"""Parse trace logs for idtracking_branch_update_s4_dataflow (S4_DataFlow)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TARGET_FILE = "src/jinja2/idtracking.py"
TARGET_FUNC = "jinja2.idtracking.Symbols.branch_update"
TARGET_START_LINE = 121
TARGET_END_LINE = 143
TRACKED_VARIABLES = (
    "branch_symbols",
    "stores",
    "branch",
    "sym",
    "name",
    "target",
    "outer_target",
)

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)"
)


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


def _load_target_events(trace_log: Path) -> list[dict[str, str | int]]:
    if not trace_log.is_file():
        _fail(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        _fail(f"trace log is empty: {trace_log}")

    events: list[dict[str, str | int]] = []
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


@dataclass(frozen=True)
class LineEffect:
    uses: tuple[str, ...]
    defs: tuple[str, ...]


class _FunctionDefUseAnalyzer(ast.NodeVisitor):
    """Collect per-line defs and uses for locals in a single function."""

    def __init__(self, tracked: set[str]) -> None:
        self.tracked = tracked
        self.line_effects: dict[int, LineEffect] = {}
        self.param_defs: dict[str, int] = {}
        self._buckets: dict[int, dict[str, set[str]]] = {}

    def _ensure(self, lineno: int) -> dict[str, set[str]]:
        if lineno not in self._buckets:
            self._buckets[lineno] = {"uses": set(), "defs": set()}
        return self._buckets[lineno]

    def _add_use(self, lineno: int, name: str) -> None:
        if name not in self.tracked:
            return
        buckets = self._ensure(lineno)
        buckets["uses"].add(name)

    def _add_def(self, lineno: int, name: str) -> None:
        if name not in self.tracked:
            return
        buckets = self._ensure(lineno)
        buckets["defs"].add(name)

    def _finalize_line(self, lineno: int, buckets: dict[str, set[str]]) -> None:
        self.line_effects[lineno] = LineEffect(
            tuple(sorted(buckets["uses"])),
            tuple(sorted(buckets["defs"])),
        )

    def _collect_names(
        self,
        node: ast.AST,
        *,
        lineno: int,
        mode: str,
    ) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                if mode == "use" and isinstance(child.ctx, ast.Load):
                    self._add_use(lineno, child.id)
                elif mode == "def" and isinstance(child.ctx, ast.Store):
                    self._add_def(lineno, child.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for arg in node.args.args + node.args.kwonlyargs:
            if arg.arg in self.tracked:
                self.param_defs[arg.arg] = node.lineno
        for child in node.body:
            self.visit(child)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        if node.value is not None:
            self._collect_names(node.value, lineno=lineno, mode="use")
            self._collect_names(node.target, lineno=lineno, mode="def")
        self._finalize_line(lineno, buckets)

    def visit_Assign(self, node: ast.Assign) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.value, lineno=lineno, mode="use")
        for target in node.targets:
            self._collect_names(target, lineno=lineno, mode="use")
            self._collect_names(target, lineno=lineno, mode="def")
        self._finalize_line(lineno, buckets)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.target, lineno=lineno, mode="use")
        self._collect_names(node.value, lineno=lineno, mode="use")
        self._collect_names(node.target, lineno=lineno, mode="def")
        self._finalize_line(lineno, buckets)

    def visit_For(self, node: ast.For) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.iter, lineno=lineno, mode="use")
        self._collect_names(node.target, lineno=lineno, mode="def")
        self._finalize_line(lineno, buckets)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_While(self, node: ast.While) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.test, lineno=lineno, mode="use")
        self._finalize_line(lineno, buckets)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_If(self, node: ast.If) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.test, lineno=lineno, mode="use")
        self._finalize_line(lineno, buckets)
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is None:
            return
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.value, lineno=lineno, mode="use")
        self._finalize_line(lineno, buckets)

    def visit_Expr(self, node: ast.Expr) -> None:
        lineno = node.lineno
        buckets = self._ensure(lineno)
        self._collect_names(node.value, lineno=lineno, mode="use")
        self._finalize_line(lineno, buckets)


def _load_line_effects(
    source_path: Path, tracked: set[str]
) -> tuple[dict[int, LineEffect], dict[str, int]]:
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    target_func: ast.FunctionDef | None = None
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "Symbols":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "branch_update":
                    target_func = item
                    break
    if target_func is None:
        _fail(f"could not locate branch_update in {source_path}")

    analyzer = _FunctionDefUseAnalyzer(tracked)
    analyzer.visit(target_func)
    return analyzer.line_effects, analyzer.param_defs


def _simulate_invocation(
    executed_lines: list[int],
    line_effects: dict[int, LineEffect],
    param_defs: dict[str, int],
    tracked: set[str],
) -> set[tuple[str, int, int]]:
    last_def: dict[str, int] = dict(param_defs)
    pairs: set[tuple[str, int, int]] = set()

    for lineno in executed_lines:
        effect = line_effects.get(lineno, LineEffect((), ()))
        for var in effect.uses:
            if var in tracked and var in last_def:
                pairs.add((var, last_def[var], lineno))
        for var in effect.defs:
            last_def[var] = lineno

    return pairs


def _compute_def_use_pairs(
    events: list[dict[str, str | int]],
    line_effects: dict[int, LineEffect],
    param_defs: dict[str, int],
    tracked: set[str],
) -> list[dict[str, int | str]]:
    all_pairs: set[tuple[str, int, int]] = set()
    invocation_lines: list[list[int]] = []

    for event in events:
        kind = str(event["event"])
        lineno = int(event["lineno"])
        if kind == "call":
            invocation_lines.append([])
            continue
        if not invocation_lines:
            continue
        if kind in ("return", "exception"):
            executed = invocation_lines.pop()
            all_pairs |= _simulate_invocation(
                executed, line_effects, param_defs, tracked
            )
            continue
        if kind == "line" and TARGET_START_LINE <= lineno <= TARGET_END_LINE:
            invocation_lines[-1].append(lineno)

    if invocation_lines:
        _fail("trace ended while still inside branch_update")

    line_event_count = sum(
        1
        for event in events
        if event["event"] == "line"
        and TARGET_START_LINE <= int(event["lineno"]) <= TARGET_END_LINE
    )
    if line_event_count < 40:
        _fail(
            f"only {line_event_count} line events in branch_update; need at least 40"
        )

    distinct_lines = {
        int(event["lineno"])
        for event in events
        if event["event"] == "line"
        and TARGET_START_LINE <= int(event["lineno"]) <= TARGET_END_LINE
    }
    if len(distinct_lines) < 8:
        _fail(
            f"only {len(distinct_lines)} distinct executed lines in branch_update; "
            f"need at least 8"
        )

    result = [
        {"variable": var, "def_line": def_line, "use_line": use_line}
        for var, def_line, use_line in sorted(all_pairs)
    ]
    if not result:
        _fail("computed zero def-use pairs")
    return result


def _build_question() -> str:
    tracked = ", ".join(f"`{name}`" for name in TRACKED_VARIABLES)
    return (
        "Consider the pytest test identified by "
        "`jinja_qa/idtracking_branch_update_s4_dataflow/files/testcase.py::"
        "IdtrackingBranchUpdateS4DataflowTest::"
        "test_direct_branch_update_merges_symbol_tables` (test class "
        "`IdtrackingBranchUpdateS4DataflowTest`, test method "
        "`test_direct_branch_update_merges_symbol_tables`). "
        "During that single test run, the function "
        f"`{TARGET_FUNC}` in `{TARGET_FILE}` is executed. "
        "Line numbers are absolute, 1-based, and refer to "
        f"`{TARGET_FILE}` as it exists in the repository; for multi-line "
        "statements, attribute executed-line events to the line where that "
        "statement begins. Decorator lines and docstring lines are never "
        "executed and must not appear. "
        "A def-use pair is an object with keys `variable`, `def_line`, and "
        "`use_line`. Track only these local variable names: "
        f"{tracked}. "
        "Define a def as a binding created by a function parameter or by an "
        "ordinary assignment (`x = ...`); parameters count as defined on the "
        f"`def` line of `branch_update` (line {TARGET_START_LINE}). "
        "A variable annotation without assignment is not a def. "
        "Define a use as any read of the variable's current value on a line "
        "within the function body. On a line that both defines and uses the "
        "same variable, count the use before the new def; augmented "
        "assignment (`x += 1`) is treated as a use of the prior value "
        "followed by a new def on that line (this function contains no "
        "augmented assignments). "
        "A `for x in ...` header defines `x` on the header line; a `while "
        "...` header does not define loop variables. Comprehension-local "
        "names are out of scope and are not tracked. "
        "Aggregate over every invocation of `branch_update` during the test "
        "run (each `call` event starts a new invocation). Within one "
        "invocation, process executed lines in chronological order; when a "
        "line executes, record one pair for each tracked use on that line "
        "paired with the most recent def of the same variable that is still "
        "active (not yet overwritten by a later def in that invocation). "
        "Union pairs from all invocations, remove duplicates, and sort the "
        "final list by `variable` ascending, then `def_line` ascending, then "
        "`use_line` ascending. "
        "Report the answer as a JSON object with exactly one key, "
        "`observed_def_use_pairs`, whose value is a JSON array of objects "
        "each having keys `variable` (string), `def_line` (integer), and "
        "`use_line` (integer)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[3] / TARGET_FILE,
    )
    args = parser.parse_args()

    tracked = set(TRACKED_VARIABLES)
    events = _load_target_events(args.trace_log)
    line_effects, param_defs = _load_line_effects(args.source, tracked)
    pairs = _compute_def_use_pairs(events, line_effects, param_defs, tracked)

    oracle_answer = {"observed_def_use_pairs": pairs}
    payload = {
        "question_kind": "S4_DataFlow",
        "question": _build_question(),
        "template_answer": {
            "observed_def_use_pairs": [
                {
                    "def_line": "int",
                    "use_line": "int",
                    "variable": "str",
                }
            ]
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
