#!/usr/bin/env python3
"""Parse trace log into S4_DataFlow oracle for divide_line."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

TARGET_FILE = "rich/_wrap.py"
TARGET_FUNC = "rich._wrap.divide_line"
DEF_LINE = 26

TRACKED_VARIABLES = (
    "_cell_len",
    "append",
    "break_positions",
    "cell_offset",
    "fold",
    "folded_word",
    "last",
    "line",
    "remaining_space",
    "start",
    "text",
    "width",
    "word",
    "word_fits_remaining_space",
    "word_length",
)

LINE_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<lineno>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(TARGET_FILE):
        return TARGET_FILE
    idx = normalized.find(TARGET_FILE)
    if idx != -1:
        return TARGET_FILE
    return normalized


def _load_line_operations(source_path: Path) -> dict[int, list[tuple[str, str]]]:
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    func_def: ast.FunctionDef | None = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "divide_line":
            func_def = node
            break
    if func_def is None:
        raise SystemExit(f"Could not find divide_line in {source_path}")

    tracked = set(TRACKED_VARIABLES)
    line_ops: dict[int, list[tuple[str, str]]] = defaultdict(list)

    def record_use(lineno: int, name: str) -> None:
        if name in tracked:
            line_ops[lineno].append(("use", name))

    def record_def(lineno: int, name: str) -> None:
        if name in tracked:
            line_ops[lineno].append(("def", name))

    class Collector(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, ast.Load):
                record_use(node.lineno, node.id)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            self.visit(node.value)

        def visit_Subscript(self, node: ast.Subscript) -> None:
            self.visit(node.value)
            self.visit(node.slice)

        def visit_Assign(self, node: ast.Assign) -> None:
            self.visit(node.value)
            for target in node.targets:
                self.visit(target)
                if isinstance(target, ast.Name):
                    record_def(target.lineno, target.id)
                elif isinstance(target, ast.Tuple):
                    for element in target.elts:
                        if isinstance(element, ast.Name):
                            record_def(element.lineno, element.id)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if node.value is not None:
                self.visit(node.value)
            self.visit(node.target)
            if isinstance(node.target, ast.Name):
                record_def(node.target.lineno, node.target.id)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self.visit(node.value)
            self.visit(node.target)
            if isinstance(node.target, ast.Name):
                record_use(node.target.lineno, node.target.id)
                record_def(node.target.lineno, node.target.id)

        def visit_For(self, node: ast.For) -> None:
            self.visit(node.iter)
            if isinstance(node.target, ast.Name):
                record_def(node.target.lineno, node.target.id)
            elif isinstance(node.target, ast.Tuple):
                for element in node.target.elts:
                    if isinstance(element, ast.Name):
                        record_def(element.lineno, element.id)
            for child in node.body:
                self.visit(child)
            for child in node.orelse:
                self.visit(child)

        def visit_While(self, node: ast.While) -> None:
            self.visit(node.test)
            for child in node.body:
                self.visit(child)
            for child in node.orelse:
                self.visit(child)

        def visit_If(self, node: ast.If) -> None:
            self.visit(node.test)
            for child in node.body:
                self.visit(child)
            for child in node.orelse:
                self.visit(child)

        def visit_Return(self, node: ast.Return) -> None:
            if node.value is not None:
                self.visit(node.value)

        def visit_Expr(self, node: ast.Expr) -> None:
            self.visit(node.value)

    collector = Collector()
    for stmt in func_def.body:
        collector.visit(stmt)

    for name in ("fold", "text", "width"):
        line_ops[DEF_LINE].insert(0, ("def", name))

    return dict(line_ops)


def _load_return_lines(source_path: Path) -> set[int]:
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    func_def: ast.FunctionDef | None = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "divide_line":
            func_def = node
            break
    if func_def is None:
        raise SystemExit(f"Could not find divide_line in {source_path}")

    return_lines: set[int] = set()

    class ReturnCollector(ast.NodeVisitor):
        def visit_Return(self, node: ast.Return) -> None:
            return_lines.add(node.lineno)

    collector = ReturnCollector()
    for stmt in func_def.body:
        collector.visit(stmt)
    return return_lines


def _parse_trace_events(trace_log: Path) -> list[dict[str, int | str]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    events: list[dict[str, int | str]] = []
    for raw_line in text.splitlines():
        if TARGET_FUNC not in raw_line:
            continue
        match = LINE_EVENT_RE.match(raw_line)
        if not match:
            continue
        file_path = _normalize_path(match.group("file"))
        if file_path != TARGET_FILE:
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
            f"No trace events found for {TARGET_FUNC} in {trace_log}"
        )
    return events


def _compute_def_use_pairs(
    events: list[dict[str, int | str]],
    line_ops: dict[int, list[tuple[str, str]]],
    return_lines: set[int],
) -> list[dict[str, int | str]]:
    observed: set[tuple[str, int, int]] = set()
    current_def: dict[str, int] = {}
    active = False

    for event in events:
        event_type = str(event["event"])
        lineno = int(event["lineno"])
        if event_type == "call":
            if not active:
                active = True
                current_def = {}
                for op, name in line_ops.get(DEF_LINE, []):
                    if op == "def" and name in TRACKED_VARIABLES:
                        current_def[name] = DEF_LINE
            continue
        if event_type == "return":
            if active and lineno in return_lines:
                active = False
                current_def = {}
            continue
        if not active or event_type != "line":
            continue

        for op, name in line_ops.get(lineno, []):
            if op == "use":
                if name not in current_def:
                    continue
                observed.add((name, current_def[name], lineno))
            elif op == "def":
                current_def[name] = lineno

    pairs = [
        {
            "def_line": def_line,
            "use_line": use_line,
            "variable": variable,
        }
        for variable, def_line, use_line in observed
    ]
    pairs.sort(key=lambda item: (item["variable"], item["def_line"], item["use_line"]))
    return pairs


QUESTION = """\
During pytest run of \
rich_qa/wrap_divide_line_s4_dataflow/files/testcase.py::TestDivideLineDataFlow::test_divide_line_dataflow, \
consider the single invocation of rich._wrap.divide_line in rich/_wrap.py \
(source lines 26-78) performed by that test method. The test calls divide_line \
directly with programmatically built text and width arguments.

Track exactly these fifteen local variables of divide_line: _cell_len, append, \
break_positions, cell_offset, fold, folded_word, last, line, remaining_space, \
start, text, width, word, word_fits_remaining_space, and word_length. Do not \
track attributes (for example word.rstrip counts as a use of the local name word), \
parameters of nested calls, globals, or comprehension temporaries.

Definition rules (1-based line numbers in rich/_wrap.py as checked into the repository):

- Function parameters text, width, and fold are defined at line 26 (the def line).
- A simple assignment or annotated assignment to a name defines that name on the \
statement's first source line.
- A for-loop header (for start, _end, word in words(text) or for last, line in \
loop_last(...)) defines each unpacked loop target on the line where the for \
statement begins.
- An augmented assignment (+=) both uses the target's current value and then \
defines the target on that same line; the use is ordered before the definition \
within the line (for example cell_offset += _cell_len(word) first uses cell_offset, \
then defines cell_offset).
- For multi-line statements, only the line where the statement begins is numbered.

Use rules:

- Any load of a tracked name in an expression is a use on that source line.
- Augmented assignment counts the pre-update read of its target as a use on that line.

An observation is one executed use of a tracked name at source line L during the \
invocation, attributed to the definition line D that was the most recent definition \
of that name still in effect at the moment of the use (standard reaching-definitions \
semantics). If a name has no prior definition in that invocation, the use is ignored. \
Uses inside loops count once per time the containing line executes.

Collect every unique tuple (variable, def_line, use_line) that occurs at least once. \
Omit pairs that never occur.

Report observed_def_use_pairs: a JSON list of objects, each with exactly these \
keys in this order when serialized:

- def_line (int): 1-based definition line in rich/_wrap.py
- use_line (int): 1-based use line in rich/_wrap.py
- variable (str): one of the fifteen tracked names

Sort the list ascending by variable, then def_line, then use_line. Each triple \
appears at most once.

Line numbers never refer to decorator lines or docstring-only lines inside \
divide_line; only executable statements in the function body and the def line \
for parameters may appear.\
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "rich" / "_wrap.py",
    )
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"Target source not found: {args.source}")

    line_ops = _load_line_operations(args.source)
    return_lines = _load_return_lines(args.source)
    events = _parse_trace_events(args.trace_log)

    line_events = [event for event in events if event["event"] == "line"]
    if len(line_events) < 40:
        raise SystemExit(
            f"Insufficient line events for target: {len(line_events)} < 40"
        )
    distinct_lines = {int(event["lineno"]) for event in line_events}
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"Insufficient distinct executed lines: {len(distinct_lines)} < 8"
        )

    observed_def_use_pairs = _compute_def_use_pairs(events, line_ops, return_lines)
    if len(observed_def_use_pairs) < 8:
        raise SystemExit(
            f"Insufficient def-use pairs: {len(observed_def_use_pairs)} < 8"
        )

    leaf_count = 0
    for pair in observed_def_use_pairs:
        leaf_count += 3
    if leaf_count < 21:
        raise SystemExit(f"Insufficient answer leaves: {leaf_count} < 21")

    oracle_answer = {"observed_def_use_pairs": observed_def_use_pairs}
    template_answer = {
        "observed_def_use_pairs": [
            {
                "def_line": "int",
                "use_line": "int",
                "variable": "str",
            }
        ]
    }

    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))


if __name__ == "__main__":
    main()
