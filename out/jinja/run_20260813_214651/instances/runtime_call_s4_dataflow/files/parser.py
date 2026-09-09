#!/usr/bin/env python3
"""Parse trace logs for Context.call observed def-use pairs."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

TARGET_FILE = "src/jinja2/runtime.py"
TARGET_FUNC = "jinja2.runtime.Context.call"
TRACKED_VARIABLES = ("__self", "__obj", "args", "kwargs", "pass_arg")
PARAM_NAMES = ("__self", "__obj", "args", "kwargs")

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    return match.groupdict()


def _name_loads(node: ast.AST, tracked: set[str]) -> list[tuple[int, str]]:
    loads: list[tuple[int, str]] = []
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Name)
            and child.id in tracked
            and isinstance(child.ctx, ast.Load)
        ):
            loads.append((child.lineno, child.id))
    return loads


def _find_call_function(tree: ast.Module) -> tuple[ast.FunctionDef, int]:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Context":
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "call":
                return item, item.lineno
    raise SystemExit(f"Could not find Context.call in {TARGET_FILE}")


def build_line_ops(repo_root: Path) -> tuple[dict[int, list[tuple[str, str]]], int]:
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        raise SystemExit(f"Target source not found: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    func_node, def_line = _find_call_function(tree)
    tracked = set(TRACKED_VARIABLES)
    line_ops: dict[int, list[tuple[str, str]]] = defaultdict(list)

    for name in PARAM_NAMES:
        line_ops[def_line].append(("def", name))

    class BodyVisitor(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:
            for lineno, var in _name_loads(node.value, tracked):
                line_ops[lineno].append(("use", var))
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in tracked:
                    line_ops[target.lineno].append(("def", target.id))

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            if isinstance(node.target, ast.Name) and node.target.id in tracked:
                line_ops[node.target.lineno].append(("use", node.target.id))
            for lineno, var in _name_loads(node.value, tracked):
                line_ops[lineno].append(("use", var))
            if isinstance(node.target, ast.Name) and node.target.id in tracked:
                line_ops[node.target.lineno].append(("def", node.target.id))

        def visit_For(self, node: ast.For) -> None:
            if isinstance(node.target, ast.Name) and node.target.id in tracked:
                line_ops[node.lineno].append(("def", node.target.id))
            for lineno, var in _name_loads(node.iter, tracked):
                line_ops[lineno].append(("use", var))
            for stmt in node.body:
                self.visit(stmt)
            for stmt in node.orelse:
                self.visit(stmt)

        def visit_comprehension(self, node: ast.comprehension) -> None:
            if isinstance(node.target, ast.Name) and node.target.id in tracked:
                line_ops[node.target.lineno].append(("def", node.target.id))
            for lineno, var in _name_loads(node.iter, tracked):
                line_ops[lineno].append(("use", var))
            for expr in node.ifs:
                for lineno, var in _name_loads(expr, tracked):
                    line_ops[lineno].append(("use", var))

        def visit_If(self, node: ast.If) -> None:
            for lineno, var in _name_loads(node.test, tracked):
                line_ops[lineno].append(("use", var))
            for stmt in node.body:
                self.visit(stmt)
            for stmt in node.orelse:
                self.visit(stmt)

        def visit_Try(self, node: ast.Try) -> None:
            for stmt in node.body:
                self.visit(stmt)
            for handler in node.handlers:
                for stmt in handler.body:
                    self.visit(stmt)
            for stmt in node.orelse:
                self.visit(stmt)
            for stmt in node.finalbody:
                self.visit(stmt)

        def visit_Return(self, node: ast.Return) -> None:
            if node.value is not None:
                for lineno, var in _name_loads(node.value, tracked):
                    line_ops[lineno].append(("use", var))

        def visit_Expr(self, node: ast.Expr) -> None:
            for lineno, var in _name_loads(node.value, tracked):
                line_ops[lineno].append(("use", var))

        def visit_With(self, node: ast.With) -> None:
            for item in node.items:
                for lineno, var in _name_loads(item.context_expr, tracked):
                    line_ops[lineno].append(("use", var))
                if item.optional_vars is not None and isinstance(
                    item.optional_vars, ast.Name
                ):
                    if item.optional_vars.id in tracked:
                        line_ops[item.optional_vars.lineno].append(
                            ("def", item.optional_vars.id)
                        )
            for stmt in node.body:
                self.visit(stmt)

    for stmt in func_node.body:
        BodyVisitor().visit(stmt)

    return dict(line_ops), def_line


def harvest_def_use_pairs(
    trace_log: Path,
    line_ops: dict[int, list[tuple[str, str]]],
    def_line: int,
) -> list[dict[str, int | str]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    target_events = 0
    current_defs: dict[str, int] = {}
    observed: set[tuple[str, int, int]] = set()
    pairs: list[dict[str, int | str]] = []

    def reset_parameters() -> None:
        nonlocal current_defs
        current_defs = {name: def_line for name in PARAM_NAMES}

    def record_use(variable: str, use_line: int) -> None:
        if variable not in current_defs:
            return
        key = (variable, current_defs[variable], use_line)
        if key in observed:
            return
        observed.add(key)
        pairs.append(
            {
                "variable": variable,
                "def_line": current_defs[variable],
                "use_line": use_line,
            }
        )

    def apply_line(lineno: int) -> None:
        for op_kind, variable in line_ops.get(lineno, []):
            if op_kind == "use":
                record_use(variable, lineno)
            else:
                current_defs[variable] = lineno

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        event = parsed["event"]
        lineno = int(parsed["lineno"])

        if event == "call":
            reset_parameters()
        elif event == "line":
            apply_line(lineno)
        elif event == "return":
            current_defs = {}

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    if not pairs:
        raise SystemExit(
            f"Trace contains {target_events} target events but zero def-use pairs"
        )

    pairs.sort(key=lambda item: (item["variable"], item["def_line"], item["use_line"]))
    return pairs


def build_question(def_line: int) -> str:
    tracked = ", ".join(f"`{name}`" for name in TRACKED_VARIABLES)
    return (
        "Consider the single test method "
        "`jinja_qa/runtime_call_s4_dataflow/files/testcase.py::"
        "TestContextCallDataFlow::test_context_call_def_use_dataflow`.\n\n"
        "That test calls `Context.call` **directly** on a `Context` instance "
        f"from `jinja2.runtime` (see `{TARGET_FILE}`).\n\n"
        "Target function: `jinja2.runtime.Context.call` (the method whose "
        f"`def` begins at line {def_line} of `{TARGET_FILE}`).\n\n"
        f"Track these local variable names only: {tracked}.\n\n"
        "A **def** is a binding or assignment to the variable: function "
        f"parameters count as defined at line {def_line} (the `def` line); "
        "each ordinary assignment creates a new def on that assignment's "
        "physical line. A **use** is any read of the variable on a line "
        "during execution (including reads in conditions, call arguments, "
        "attribute access receivers, and subscripts).\n\n"
        "Augmented assignment (`x += 1`) counts as a use of the prior value "
        "on that line followed by a new def on the same line. A `for x in "
        "...` loop header defines `x` on the header line at the start of each "
        "iteration. Comprehension-local targets are defined on the line where "
        "the comprehension appears. None of these constructs occur for the "
        "tracked names in the target function, but the rule is stated for "
        "completeness.\n\n"
        "An **observed def-use pair** is `{variable, def_line, use_line}` "
        "where the value established at `def_line` is read at `use_line` "
        "before that variable is defined again on a later executed line. "
        "Collect every such pair that occurs in any invocation of "
        f"`{TARGET_FUNC}` during the test run. When the same triple appears "
        "in multiple invocations, include it once (deduplicate exact "
        "triples).\n\n"
        "Line numbers are absolute, 1-based, in "
        f"`{TARGET_FILE}` as it exists in the repository. For multi-line "
        "statements, the executed `line` event corresponds to the physical "
        "line where that sub-expression or statement begins. Decorator lines "
        "and docstrings are not execution lines for this question.\n\n"
        "Within a single line that both reads and assigns a variable, process "
        "sub-expressions in Python evaluation order (right-hand side and "
        "call arguments before assignment targets).\n\n"
        "Sort the final list by `variable` ascending, then `def_line` "
        "ascending, then `use_line` ascending.\n\n"
        "Return JSON with exactly one top-level key `observed_def_use_pairs` "
        "whose value is a list of objects, each with keys `variable` (string), "
        "`def_line` (integer), and `use_line` (integer)."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args()

    line_ops, def_line = build_line_ops(args.repo_root)
    pairs = harvest_def_use_pairs(args.trace_log, line_ops, def_line)

    oracle_answer = {"observed_def_use_pairs": pairs}
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
        "question": build_question(def_line),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
