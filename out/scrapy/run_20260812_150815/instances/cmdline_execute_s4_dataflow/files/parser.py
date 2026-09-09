from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/cmdline.py"
TARGET_FUNC = "scrapy.cmdline.execute"
TRACKED_VARIABLES = (
    "args",
    "argv",
    "cmd",
    "cmdname",
    "editor",
    "inproject",
    "opts",
    "parser",
    "settings",
)
TRACKED_SET = set(TRACKED_VARIABLES)

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


class FunctionAccessCollector(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef):
        self.root = root
        self.defs: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}

    @staticmethod
    def _add(table: dict[int, set[str]], line: int, name: str) -> None:
        table.setdefault(line, set()).add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is not self.root:
            return
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED_SET:
            return
        if isinstance(node.ctx, ast.Load):
            self._add(self.uses, node.lineno, node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._add(self.defs, node.lineno, node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in TRACKED_SET:
            self._add(self.uses, node.target.lineno, node.target.id)
            self._add(self.defs, node.target.lineno, node.target.id)
        else:
            self.visit(node.target)
        self.visit(node.value)


def source_accesses(
    repo_root: Path,
) -> tuple[int, dict[int, set[str]], dict[int, set[str]]]:
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    targets = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute"
    ]
    if len(targets) != 1:
        fail(f"expected exactly one top-level execute definition, found {len(targets)}")
    target = targets[0]
    def_line = target.lineno

    collector = FunctionAccessCollector(target)
    collector.visit(target)
    collector.defs.setdefault(def_line, set()).update(
        argument.arg
        for argument in (
            *target.args.posonlyargs,
            *target.args.args,
            *target.args.kwonlyargs,
        )
        if argument.arg in TRACKED_SET
    )
    return def_line, collector.defs, collector.uses


def parse_target_events(trace_path: Path) -> list[tuple[str, int]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((match.group("event"), int(match.group("line"))))
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event == "call" for event, _ in events):
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    return events


def build_answer(
    events: list[tuple[str, int]],
    def_line: int,
    definitions: dict[int, set[str]],
    uses: dict[int, set[str]],
) -> dict[str, object]:
    current_defs: dict[str, int] | None = None
    pairs: set[tuple[str, int, int]] = set()
    invocation_count = 0

    for event, line in events:
        if event == "call":
            invocation_count += 1
            current_defs = {
                variable: def_line for variable in definitions.get(def_line, ())
            }
            continue
        if current_defs is None:
            continue
        if event == "line":
            for variable in sorted(uses.get(line, ())):
                if variable not in current_defs:
                    fail(
                        f"use of tracked variable {variable!r} at line {line} "
                        "has no reaching definition"
                    )
                pairs.add((variable, current_defs[variable], line))
            for variable in sorted(definitions.get(line, ())):
                current_defs[variable] = line
        elif event == "return":
            current_defs = None

    if invocation_count == 0:
        fail(f"trace contains zero invocations for {TARGET_FUNC}")
    if len(pairs) < 8:
        fail(f"only {len(pairs)} unique def-use pairs were observed; need at least 8")
    return {
        "observed_def_use_pairs": [
            {"def_line": def_line, "use_line": use_line, "variable": variable}
            for variable, def_line, use_line in sorted(pairs)
        ]
    }


def question_text() -> str:
    tracked = ", ".join(f"`{name}`" for name in TRACKED_VARIABLES)
    return (
        "Run the single pytest test "
        "`scrapy_qa/cmdline_execute_s4_dataflow/files/testcase.py::"
        "CmdlineExecuteDataFlowTest::test_generated_execute_schedule`. Across all "
        "invocations made by that test of `scrapy.cmdline.execute` in "
        "`scrapy/cmdline.py`, what are all unique observed def-use pairs for "
        f"exactly these local variables: {tracked}? An invocation is one call of "
        "the target function during the test run; invocations are 1-based in "
        "chronological call order, although invocation numbers are not included "
        "in the output. A def is a binding of the named local by parameter binding "
        "or assignment. Each parameter is defined at the function's `def` line, "
        "including parameters whose text appears on continuation lines. A use is "
        "an evaluation that reads the named local's current value on an executed "
        "source line. A pair records the most recent executed def that reaches "
        "that use without an intervening def of the same variable, independently "
        "within each invocation; definitions never flow between invocations. For "
        "an ordinary assignment, evaluate and record all right-hand-side uses "
        "before making the assignment's target the current def. An augmented "
        "assignment such as `total += delta` both uses the old `total` def and "
        "creates a new `total` def on that same line, in that order. A `for x in "
        "items` header uses names in the iterable expression and redefines `x` on "
        "the header line for every executed iteration. All bindings and accesses "
        "syntactically inside a list, set, or dict comprehension or generator "
        "expression are excluded, including comprehension-local variables. "
        "Attribute names and mapping keys are not locals; for example, reading "
        "`obj.value` is a use of `obj`, not of `value`. Report absolute 1-based "
        "source line numbers in the named repository file as it exists for this "
        "test. For a multi-line statement or expression, assign each def or use "
        "to the physical source line on which that binding or read begins; the "
        "function parameters are the stated exception and all use the opening "
        "`def` line. Decorator and docstring lines do not count unless one of the "
        "tracked locals is actually bound or read there. Collapse duplicate "
        "triples observed in the same or different invocations, then sort the "
        "unique entries by `variable` lexicographically ascending, then "
        "`def_line` numerically ascending, then `use_line` numerically ascending. "
        "Return exactly a JSON object with the single key "
        "`observed_def_use_pairs`. Its value is a JSON array of objects, each "
        "with exactly three keys: `def_line` (JSON integer), `use_line` (JSON "
        "integer), and `variable` (JSON string using the exact source identifier "
        "spelling, without `repr()` quotes). Do not include invocation numbers, "
        "file names, values, null placeholders, or additional keys. If no pairs "
        "were observed, the array would be empty."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    repo_root = Path(__file__).resolve().parents[3]
    def_line, definitions, uses = source_accesses(repo_root)
    answer = build_answer(
        parse_target_events(trace_path), def_line, definitions, uses
    )
    payload = {
        "question_kind": "S4_DataFlow",
        "question": question_text(),
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
