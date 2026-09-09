#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/simple_train.py"
TARGET_FUNC = "instructlab.model.simple_train.simple_train"
VARIABLES = (
    "file",
    "file_",
    "final_results_dir",
    "fpath",
    "training_results_dir",
)
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test `instruct_lab_qa/simple_train_simple_train_s4_dataflow/files/testcase.py::TestSimpleTrainDataFlow::test_seeded_model_artifacts` and consider exactly `instructlab.model.simple_train.simple_train` in `src/instructlab/model/simple_train.py`. Across all invocations during the complete test run, what unique dynamic def-use pairs are observed for the local variables `file`, `file_`, `final_results_dir`, `fpath`, and `training_results_dir`?

A “def” is an assignment or binding of one of those exact local variable names in the target function's own frame. A parameter binding counts as a def on the function's `def` line. A “use” is a read of that exact local variable's current value by code executing in that same target frame. A pair is observed when a value bound by a def reaches a later use without an intervening def of the same variable in that invocation. Process reads before writes on the same source line: augmented assignment such as a hypothetical `total += delta` is both a use of `total` reached by its old def and then a new def of `total` on that line. Each successful `for x in iterable` binding is a new def of `x` on the loop-header line for that iteration; evaluating the iterable can use an earlier definition before that new binding. A loop-header attempt that terminates by exhaustion creates no def. Comprehension induction variables belong to their comprehension frame, not the target frame, so their defs and uses are excluded; reads performed inside a comprehension frame are also excluded. Likewise, nested functions, callees, and all other frames are excluded.

An invocation is one Python `call` of exactly `instructlab.model.simple_train.simple_train`, counted 1-based in chronological order over the complete test run; calls or resumptions of nested functions, comprehensions, or callees do not create target invocations. Compute pairs independently within each invocation, take their set union across invocations, and remove exact duplicate triples only after that union. Definitions never reach from one invocation into another.

Line numbers are absolute, 1-based physical lines in the named repository file. Attribute a def or use to the physical source line containing that binding or read. For a multi-line statement or expression, execution begins at its first executable line, but any reported identifier is attributed to the physical line on which that identifier occurs. The target has no decorators, and its `def` line can appear only for a tracked parameter binding; docstring or comment lines cannot create defs or uses.

Return exactly one JSON object with the shape `{"observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]}`. Each actual `def_line` and `use_line` is a JSON integer, and `variable` is the exact source identifier as a JSON string. Sort the list by `variable` in ascending lexicographic Unicode code-point order, then by `def_line` numerically ascending, then by `use_line` numerically ascending. These fields form the complete tie-break order. Function names, values, exception types, and callees are not reported, so name-prefix, `repr()` versus `str()`, exception-name, and empty-versus-null conventions do not otherwise apply."""


class AccessCollector(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = set(tracked)
        self.defs = {name: set() for name in tracked}
        self.uses = {name: set() for name in tracked}

    def visit_Name(self, node):
        if node.id not in self.tracked:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses[node.id].add(node.lineno)
        elif isinstance(node.ctx, ast.Store):
            self.defs[node.id].add(node.lineno)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_ClassDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def visit_ListComp(self, node):
        return

    def visit_SetComp(self, node):
        return

    def visit_DictComp(self, node):
        return

    def visit_GeneratorExp(self, node):
        return


def source_accesses(source_path: Path):
    if not source_path.exists():
        raise RuntimeError(f"target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "simple_train"
        ),
        None,
    )
    if target is None:
        raise RuntimeError("cannot find target function in source")

    collector = AccessCollector(VARIABLES)
    for statement in target.body:
        collector.visit(statement)

    parameters = (
        list(target.args.posonlyargs)
        + list(target.args.args)
        + list(target.args.kwonlyargs)
    )
    if target.args.vararg:
        parameters.append(target.args.vararg)
    if target.args.kwarg:
        parameters.append(target.args.kwarg)
    parameter_names = {parameter.arg for parameter in parameters}
    for variable in VARIABLES:
        if variable in parameter_names:
            collector.defs[variable].add(target.lineno)
    return collector.defs, collector.uses, parameter_names, target.lineno


def parse_pairs(trace_path: Path, source_path: Path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    definitions, uses, parameter_names, def_line = source_accesses(source_path)
    pairs = set()
    current_defs = {}
    active = False
    target_events = 0
    invocations = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            if active:
                raise RuntimeError("overlapping target invocations are unsupported")
            invocations += 1
            active = True
            current_defs = {
                variable: def_line
                for variable in VARIABLES
                if variable in parameter_names
            }
            continue
        if not active:
            continue

        if event == "line":
            for variable in VARIABLES:
                if line in uses[variable] and variable in current_defs:
                    pairs.add((variable, current_defs[variable], line))
            for variable in VARIABLES:
                if line in definitions[variable]:
                    current_defs[variable] = line
        elif event == "return":
            active = False
            current_defs = {}

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocations == 0:
        raise RuntimeError("trace contains no target invocations")
    if active:
        raise RuntimeError("final target invocation has no return event")
    if not pairs:
        raise RuntimeError("no observed def-use pairs were computed")

    return [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {
            "observed_def_use_pairs": parse_pairs(
                args.trace_log, repo_root / TARGET_FILE
            )
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

