#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/click/exceptions.py"
TARGET_FUNC = "click.exceptions.MissingParameter.format_message"
TRACKED_VARIABLES = (
    "missing",
    "msg",
    "msg_extra",
    "param_hint",
    "param_type",
    "self",
)
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`click_qa/exceptions_format_message_s4_dataflow/files/testcase.py::TestMissingParameterDataFlow::test_seeded_missing_parameter_matrix`
and consider every invocation of
`click.exceptions.MissingParameter.format_message` in
`src/click/exceptions.py` caused by that test. What are all unique observed
def-use pairs for exactly these local-variable names: `missing`, `msg`,
`msg_extra`, `param_hint`, `param_type`, and `self`?

An invocation is one entry into exactly the named target function, counted
1-based in chronological order during this test only. Aggregate pairs from all
such invocations. Consider only execution in each target invocation's own
frame; activity in callees, nested functions, or other frames does not count.

A definition ("def") is a parameter binding or an assignment to the named
local that actually occurs during execution. Parameters count as defined on
the function's `def` line. A use is a runtime read of that local. A pair is
observed when the value from a definition reaches a use before any intervening
redefinition of that variable. For an assignment, evaluate uses of its
right-hand side before applying its definition. Augmented assignment such as
`total += step` first uses the old reaching definition of `total` and then
defines a new value on that same line. A `for x in values` header uses locals
in its iterable expression and redefines `x` once per executed iteration
before the body. Comprehension-local variables belong to the comprehension's
separate scope and neither define nor use same-named locals in the target
frame; reads captured from the target frame still count as target-frame uses.

Line numbers are absolute 1-based source line numbers in
`src/click/exceptions.py` as it exists in the repository. A parameter
definition uses the function's `def` line. Otherwise, a definition is reported
on the line where its assignment target begins, and a use on the line where
the read identifier begins. Thus, for a multi-line statement these can be
continuation lines rather than the statement's first line. Decorator and
docstring lines count only if they contain a definition or runtime read under
these rules.

Return exactly
`{"observed_def_use_pairs": [{"def_line": int, "use_line": int, "variable": str}]}`
as JSON-compatible data. Emit one object per distinct
`(variable, def_line, use_line)` triple observed across all invocations,
removing duplicates even if a triple occurs repeatedly. Sort objects by
`variable` in ascending Unicode code-point order, then by `def_line`
ascending, then by `use_line` ascending. Variable strings must be exactly the
six bare local names listed above; line values are JSON integers."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_target(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MissingParameter":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "format_message":
                    return child
    fail("could not locate MissingParameter.format_message in target source")


def def_use_lines(
    function: ast.FunctionDef,
) -> tuple[dict[int, set[str]], dict[int, set[str]], dict[str, int]]:
    tracked = set(TRACKED_VARIABLES)
    definitions: dict[int, set[str]] = {}
    uses: dict[int, set[str]] = {}
    parameter_defs: dict[str, int] = {}

    arguments = (
        list(function.args.posonlyargs)
        + list(function.args.args)
        + list(function.args.kwonlyargs)
    )
    if function.args.vararg is not None:
        arguments.append(function.args.vararg)
    if function.args.kwarg is not None:
        arguments.append(function.args.kwarg)
    for argument in arguments:
        if argument.arg in tracked:
            parameter_defs[argument.arg] = function.lineno

    class BodyVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is function:
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
            if node.id not in tracked:
                return
            if isinstance(node.ctx, ast.Load):
                uses.setdefault(node.lineno, set()).add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                definitions.setdefault(node.lineno, set()).add(node.id)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            if isinstance(node.target, ast.Name) and node.target.id in tracked:
                uses.setdefault(node.target.lineno, set()).add(node.target.id)
                definitions.setdefault(node.target.lineno, set()).add(node.target.id)
                self.visit(node.value)
                return
            self.generic_visit(node)

    BodyVisitor().visit(function)
    return definitions, uses, parameter_defs


def parse_invocations(trace_text: str) -> list[list[int]]:
    invocations: list[list[int]] = []
    current: list[int] | None = None

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        event = match.group("event")
        if event == "call":
            if current is not None:
                fail("encountered nested target call before prior invocation ended")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("encountered target line event outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            if current is None:
                fail("encountered target return event outside an invocation")
            current = None

    if current is not None:
        fail("trace ended before final target invocation returned")
    return invocations


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    invocations = parse_invocations(trace_text)
    if not invocations:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    line_event_count = sum(len(invocation) for invocation in invocations)
    if line_event_count == 0:
        fail(f"trace contains zero line events for {TARGET_FUNC}")

    repo_root = Path(__file__).resolve().parents[3]
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    source = source_path.read_text(encoding="utf-8")
    function = find_target(source)
    definitions, uses, parameter_defs = def_use_lines(function)

    pairs: set[tuple[str, int, int]] = set()
    for invocation in invocations:
        reaching = dict(parameter_defs)
        for line in invocation:
            if line < function.lineno or line > function.end_lineno:
                fail(f"target invocation contains out-of-range line event: {line}")
            for variable in uses.get(line, ()):
                if variable not in reaching:
                    fail(f"use of {variable!r} on line {line} has no reaching def")
                pairs.add((variable, reaching[variable], line))
            for variable in definitions.get(line, ()):
                reaching[variable] = line

    if not pairs:
        fail("computed no observed def-use pairs")

    observed = [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]
    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": observed},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
