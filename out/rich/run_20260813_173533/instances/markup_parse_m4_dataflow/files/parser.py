#!/usr/bin/env python3
"""Parse a trace log into an M4_DataFlow oracle for rich.markup._parse."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

QUESTION_KIND = "M4_DataFlow"
TARGET_FILE = "rich/markup.py"
TARGET_FUNC = "rich.markup._parse"
DEF_LINE = 73
TEST_CLASS = (
    "rich_qa/markup_parse_m4_dataflow/files/testcase.py::MarkupParseDataflowTest"
)
TRACKED_VARS = [
    "markup",
    "position",
    "_divmod",
    "_Tag",
    "match",
    "full_text",
    "escapes",
    "tag_text",
    "start",
    "end",
    "backslashes",
    "escaped",
    "text",
    "equals",
    "parameters",
]

QUESTION = f"""\
During pytest run {TEST_CLASS}, aggregate observations across all twelve test methods in that class (every def test_... method), in pytest collection order: test_bulk_alternating_style_tags, test_dense_param_link_tags, test_escape_ladder_variants, test_plain_runs_between_tags, test_unclosed_style_stack, test_implicit_slash_closers, test_hash_color_style_tags, test_mixed_escape_and_real_tags, test_single_character_tag_burst, test_nested_overlapping_styles, test_trailing_plain_tail, and test_leading_plain_then_tags.

The tests reach {TARGET_FUNC} only indirectly through callers such as rich.markup.render (for example via render(markup, emoji=False)); your answer must still describe def-use flow inside _parse itself.

Collect every observed def-use pair for the following local variable names only: markup, position, _divmod, _Tag, match, full_text, escapes, tag_text, start, end, backslashes, escaped, text, equals, parameters.

Definitions and uses are determined from the source of _parse in {TARGET_FILE} as it exists in the repository. A def is any binding that assigns a new value to a tracked name: function parameters (including keyword-only parameters), plain assignment, for-loop targets, and the write side of augmented assignment. The parameter markup counts as defined on line {DEF_LINE} (the def line). A use is any read of a tracked name on an executable line in the function body. The def line itself ({DEF_LINE}), decorator lines, and docstring lines are not executed and never contribute uses; only body lines reached at runtime count.

Augmented assignment (for example start += backslashes * 2 on line 93) counts as a use of the prior value on that line followed by a new def on the same line. A for-loop header such as for match in RE_TAGS.finditer(markup): defines match on the header line each time that line runs. Comprehension iteration variables are not tracked here because they are not listed above.

Process every invocation of _parse during the entire test run. _parse is a generator function. One invocation is one call event whose func equals {TARGET_FUNC} exactly and whose line number is {DEF_LINE} (the function entry). While that generator runs, Python emits additional call events at yield/resume points (for example lines 87, 92, 96, 100, and 103); those resume call events do NOT start a new invocation. For each entry call at line {DEF_LINE}, collect every line event for {TARGET_FUNC} in chronological trace order until the next entry call at line {DEF_LINE} or the end of the trace; that entire sequence belongs to one invocation. Reset active definitions only at each entry call at line {DEF_LINE}.

Within one invocation, walk those line events in chronological order. On each executed line, for every tracked use on that line, record one observation {{variable, def_line, use_line}} where def_line is the line number of the active definition of that variable (the most recent def at or before the use, not yet superseded) and use_line is the line where the use occurs. If a line both uses and defines the same variable, process all uses on that line against the prior active def before applying the new def on that line. After handling uses and defs on a line, update active defs for any names defined on that line. One observation is one such use event; a use inside a loop body contributes one observation per time that use line executes.

Sum observation counts across all invocations and all twelve test methods. Each distinct triple (variable, def_line, use_line) appears at most once in the answer; its count is the total number of observations of that triple. Pairs that never occur are omitted.

Sort the final list by variable ascending (ASCII), then def_line ascending, then use_line ascending.

Report the answer as JSON with top-level key observed_def_use_pairs whose value is a list of objects, each with exactly these keys:
- variable (str): one of the tracked names above
- def_line (int): 1-based line number in {TARGET_FILE} where the reaching definition occurred
- use_line (int): 1-based line number in {TARGET_FILE} where the variable was read
- count (int): total observations of this triple across the whole test run

Line numbers are absolute, 1-based, in {TARGET_FILE} as present in the repository. For a multi-line statement, Python reports the line event on the line where that statement begins.\
"""

TEMPLATE_ANSWER = {
    "observed_def_use_pairs": [
        {
            "count": "int",
            "def_line": "int",
            "use_line": "int",
            "variable": "str",
        },
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


def _find_parse_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_parse":
            return node
    raise SystemExit(f"could not find _parse in {TARGET_FILE}")


def _record_target_defs(
    target: ast.AST, lineno: int, tracked: set[str], line_defs: dict[int, set[str]]
) -> None:
    if isinstance(target, ast.Name):
        if target.id in tracked:
            line_defs.setdefault(lineno, set()).add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            _record_target_defs(elt, lineno, tracked, line_defs)


class _DefUseVisitor(ast.NodeVisitor):
    def __init__(
        self,
        tracked: set[str],
        line_defs: dict[int, set[str]],
        line_uses: dict[int, set[str]],
    ) -> None:
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


def _build_static_maps(
    func_node: ast.FunctionDef, tracked: set[str]
) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
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

        if event == "call" and line_no == DEF_LINE:
            if current_lines is not None:
                invocations.append(current_lines)
            current_lines = []
        elif event == "line" and current_lines is not None:
            current_lines.append(line_no)

    if current_lines is not None:
        invocations.append(current_lines)

    if matched_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not invocations:
        raise SystemExit(
            f"trace log contains no entry invocations for {TARGET_FUNC} at line {DEF_LINE}"
        )
    return invocations


def _count_pairs_for_invocation(
    executed_lines: list[int],
    line_defs: dict[int, set[str]],
    line_uses: dict[int, set[str]],
) -> Counter[tuple[str, int, int]]:
    tracked = set(TRACKED_VARS)
    active_def: dict[str, int] = {}
    for name in line_defs.get(DEF_LINE, set()):
        if name in tracked:
            active_def[name] = DEF_LINE

    counts: Counter[tuple[str, int, int]] = Counter()
    for lineno in executed_lines:
        for name in sorted(line_uses.get(lineno, set())):
            if name in active_def:
                counts[(name, active_def[name], lineno)] += 1
        for name in sorted(line_defs.get(lineno, set())):
            active_def[name] = lineno
    return counts


def _build_answer(trace_log: Path) -> dict:
    source_path = _repo_root() / TARGET_FILE
    func_node = _find_parse_function(source_path.read_text(encoding="utf-8"))
    tracked = set(TRACKED_VARS)
    line_defs, line_uses = _build_static_maps(func_node, tracked)

    total_counts: Counter[tuple[str, int, int]] = Counter()
    invocations = _parse_invocation_lines(trace_log)
    line_event_count = 0
    distinct_lines: set[int] = set()

    for executed_lines in invocations:
        line_event_count += len(executed_lines)
        distinct_lines.update(executed_lines)
        total_counts.update(
            _count_pairs_for_invocation(executed_lines, line_defs, line_uses)
        )

    if line_event_count == 0:
        raise SystemExit("trace contains zero line events for _parse")

    observed = [
        {
            "variable": variable,
            "def_line": def_line,
            "use_line": use_line,
            "count": count,
        }
        for (variable, def_line, use_line), count in sorted(total_counts.items())
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
