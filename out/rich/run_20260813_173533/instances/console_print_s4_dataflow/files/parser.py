#!/usr/bin/env python3
"""Parse a trace log into an S4_DataFlow oracle for Console.print."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

QUESTION_KIND = "S4_DataFlow"
TARGET_FILE = "rich/console.py"
TARGET_FUNC = "rich.console.Console.print"
DEF_LINE = 1652
TRACKED_VARS = [
    "objects",
    "crop",
    "render_hooks",
    "renderables",
    "render_options",
    "new_segments",
    "style",
    "soft_wrap",
    "hook",
    "renderable",
]

QUESTION = """\
During pytest run rich_qa/console_print_s4_dataflow/files/testcase.py::ConsolePrintDataflowTest::test_seeded_indirect_print_dataflow, consider the function rich.console.Console.print defined in rich/console.py (the def statement begins on line 1652).

Collect every observed def-use pair for the following local variable names only: objects, crop, render_hooks, renderables, render_options, new_segments, style, soft_wrap, hook, renderable.

Definitions and uses are determined from the source of print in rich/console.py as it exists in the repository. A def is any binding that assigns a new value to a tracked name: function parameters (including *objects and keyword-only parameters), plain assignment, for-loop targets, and the write side of augmented assignment. Each parameter name counts as defined on line 1652 (the def line). A use is any read of a tracked name on an executable line in the function body. The def line itself (1652), decorator lines, and docstring lines are not executed and never contribute uses; only body lines reached at runtime count.

Augmented assignment (there are none for the tracked names in print) would count as a use of the prior value on that line followed by a new def on the same line. A for-loop header such as for hook in render_hooks: defines the loop variable on the header line each time that line runs. Comprehension iteration variables (for example segment in a generator inside an expression) are not tracked here because they are not listed above.

Process every invocation of print during the test run. An invocation is one call event for print; invocations are independent—reset active definitions at each call so parameter bindings on line 1652 apply again. Within one invocation, walk line events in chronological order for frames whose func equals rich.console.Console.print (module-qualified format: package.module.Class.method, e.g. rich.console.Console.print). On each executed line, record a def-use pair {variable, def_line, use_line} for every tracked use on that line: def_line is the line number of the active definition of that variable (the most recent def at or before the use, not yet superseded), and use_line is the line where the use occurs. If a line both uses and defines the same variable, process all uses on that line against the prior active def before applying the new def on that line. After handling uses and defs on a line, update active defs for any names defined on that line.

Include pairs from all invocations together. Deduplicate identical triples. Sort the final list by variable ascending (ASCII), then def_line ascending, then use_line ascending.

Report the answer as JSON with top-level key observed_def_use_pairs whose value is a list of objects, each with exactly these keys:
- variable (str): one of the tracked names above
- def_line (int): 1-based line number in rich/console.py where the reaching definition occurred
- use_line (int): 1-based line number in rich/console.py where the variable was read

Line numbers are absolute, 1-based, in rich/console.py as present in the repository. For a multi-line statement, Python reports the line event on the line where that statement begins.\
"""

TEMPLATE_ANSWER = {
    "observed_def_use_pairs": [
        {"def_line": "int", "use_line": "int", "variable": "str"},
    ],
}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.rfind(TARGET_FILE)
    if idx == -1:
        raise ValueError(f"trace path does not contain {TARGET_FILE!r}: {path!r}")
    return normalized[idx:]


def _find_print_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Console":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "print":
                    return item
    raise SystemExit(f"could not find Console.print in {TARGET_FILE}")


def _record_target_defs(target: ast.AST, lineno: int, tracked: set[str], line_defs: dict[int, set[str]]) -> None:
    if isinstance(target, ast.Name):
        if target.id in tracked:
            line_defs.setdefault(lineno, set()).add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _record_target_defs(elt, lineno, tracked, line_defs)


class _DefUseVisitor(ast.NodeVisitor):
    def __init__(self, tracked: set[str], line_defs: dict[int, set[str]], line_uses: dict[int, set[str]]) -> None:
        self.tracked = tracked
        self.line_defs = line_defs
        self.line_uses = line_uses

    def _add_def(self, name: str, lineno: int) -> None:
        if name in self.tracked:
            self.line_defs.setdefault(lineno, set()).add(name)

    def _add_use(self, name: str, lineno: int) -> None:
        if name in self.tracked:
            self.line_uses.setdefault(lineno, set()).add(name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self._add_def(node.id, node.lineno)
        elif isinstance(node.ctx, ast.Load):
            self._add_use(node.id, node.lineno)

    def visit_For(self, node: ast.For) -> None:
        _record_target_defs(node.target, node.lineno, self.tracked, self.line_defs)
        self.visit(node.iter)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)  # type: ignore[arg-type]

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        for gen in node.generators:
            _record_target_defs(gen.target, node.lineno, self.tracked, self.line_defs)
            self.visit(gen.iter)
            for clause in gen.ifs:
                self.visit(clause)
        self.visit(node.elt)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        for gen in node.generators:
            _record_target_defs(gen.target, node.lineno, self.tracked, self.line_defs)
            self.visit(gen.iter)
            for clause in gen.ifs:
                self.visit(clause)
        self.visit(node.elt)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        for gen in node.generators:
            _record_target_defs(gen.target, node.lineno, self.tracked, self.line_defs)
            self.visit(gen.iter)
            for clause in gen.ifs:
                self.visit(clause)
        self.visit(node.elt)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        for gen in node.generators:
            _record_target_defs(gen.target, node.lineno, self.tracked, self.line_defs)
            self.visit(gen.iter)
            for clause in gen.ifs:
                self.visit(clause)
        self.visit(node.key)
        self.visit(node.value)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        return

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._add_use(node.target.id, node.lineno)
            self._add_def(node.target.id, node.lineno)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            self._add_def(node.target.id, node.lineno)
            self.visit(node.value)
        else:
            self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self._add_def(node.arg, DEF_LINE)


def _build_static_maps(func_node: ast.FunctionDef, tracked: set[str]) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    line_defs: dict[int, set[str]] = {}
    line_uses: dict[int, set[str]] = {}
    visitor = _DefUseVisitor(tracked, line_defs, line_uses)
    for arg in func_node.args.posonlyargs + func_node.args.args + func_node.args.kwonlyargs:
        visitor.visit(arg)
    if func_node.args.vararg is not None:
        visitor.visit(func_node.args.vararg)
    if func_node.args.kwarg is not None:
        visitor.visit(func_node.args.kwarg)
    visitor.visit(func_node)
    return line_defs, line_uses


def _parse_invocation_lines(trace_log: Path) -> list[list[int]]:
    if not trace_log.is_file():
        raise SystemExit(f"trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"trace log is empty: {trace_log}")

    invocations: list[list[int]] = []
    current_lines: list[int] | None = None
    matched_events = 0

    for raw_line in text.splitlines():
        match = TRACE_LINE_RE.match(raw_line)
        if not match:
            continue

        if _normalize_file(match.group("file")) != TARGET_FILE:
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        matched_events += 1
        event = match.group("event")
        line_no = int(match.group("line"))

        if event == "call":
            current_lines = []
            invocations.append(current_lines)
        elif event == "line" and current_lines is not None:
            current_lines.append(line_no)
        elif event == "return":
            current_lines = None

    if matched_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    return invocations


def _pairs_for_invocation(
    executed_lines: list[int],
    line_defs: dict[int, set[str]],
    line_uses: dict[int, set[str]],
) -> set[tuple[str, int, int]]:
    tracked = set(TRACKED_VARS)
    active_def: dict[str, int] = {}
    for name in line_defs.get(DEF_LINE, set()):
        if name in tracked:
            active_def[name] = DEF_LINE

    pairs: set[tuple[str, int, int]] = set()
    for lineno in executed_lines:
        for name in sorted(line_uses.get(lineno, set())):
            if name in active_def:
                pairs.add((name, active_def[name], lineno))
        for name in sorted(line_defs.get(lineno, set())):
            active_def[name] = lineno
    return pairs


def _build_answer(trace_log: Path) -> dict:
    source_path = _repo_root() / TARGET_FILE
    func_node = _find_print_function(source_path.read_text(encoding="utf-8"))
    tracked = set(TRACKED_VARS)
    line_defs, line_uses = _build_static_maps(func_node, tracked)

    all_pairs: set[tuple[str, int, int]] = set()
    invocations = _parse_invocation_lines(trace_log)
    line_event_count = 0
    distinct_lines: set[int] = set()

    for executed_lines in invocations:
        line_event_count += len(executed_lines)
        distinct_lines.update(executed_lines)
        all_pairs.update(_pairs_for_invocation(executed_lines, line_defs, line_uses))

    if line_event_count == 0:
        raise SystemExit("trace contains zero line events for Console.print")

    observed = [
        {"variable": variable, "def_line": def_line, "use_line": use_line}
        for variable, def_line, use_line in sorted(all_pairs)
    ]

    if not observed:
        raise SystemExit("computed zero def-use pairs")

    return {"observed_def_use_pairs": observed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    oracle_answer = _build_answer(args.trace_log)

    payload = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
