#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


TARGET_FILE = "src/instructlab/model/accelerated_train.py"
TARGET_FUNC = "instructlab.model.accelerated_train._run_phased_training"
VARIABLES = (
    "best_checkpoint",
    "next_checkpoint",
    "output_checkpoint",
    "phase1_checkpoints",
    "phase1_checkpoints_dir_hf",
    "phase2_checkpoints_dir",
    "phase2_eval_cache",
    "phase_model",
)
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test `instruct_lab_qa/accelerated_train_run_phased_training_m4_dataflow/files/testcase.py::TestPhasedTrainingDataFlow::test_seeded_phase_entry_paths` and consider exactly `instructlab.model.accelerated_train._run_phased_training` in `src/instructlab/model/accelerated_train.py`. Across all invocations during the complete test run, what unique dynamic def-use pairs are observed for the exact local variables `best_checkpoint`, `next_checkpoint`, `output_checkpoint`, `phase1_checkpoints`, `phase1_checkpoints_dir_hf`, `phase2_checkpoints_dir`, `phase2_eval_cache`, and `phase_model`?

A “def” is an assignment or binding of one of those exact local variable names in the target function's own frame. A parameter binding counts as a def on the function's `def` line. A “use” is a read of that exact local variable's current value by code executing in that same target frame. A pair is observed when a value bound by a def reaches a later use without an intervening def of the same variable in that invocation. On a source line containing both reads and writes, process all reads before all writes: thus a self-referential ordinary assignment such as a hypothetical `item = item.next` uses the old definition and then defines `item`, while augmented assignment such as `total += delta` is likewise both a use of `total` reached by its old def and then a new def of `total` on that line. Each successful `for x in iterable` binding is a new def of `x` on the loop-header line for that iteration; evaluating the iterable can use an earlier definition before that new binding, and a loop-header attempt that terminates by exhaustion creates no def. Comprehension induction variables belong to their comprehension frame, not the target frame, so their defs and uses are excluded; reads performed inside a comprehension frame are also excluded. Nested functions, callees, generators, and all other frames are excluded.

An invocation is one Python `call` of exactly `instructlab.model.accelerated_train._run_phased_training`, counted 1-based in chronological order over the complete test run. Calls or resumptions of nested functions, comprehensions, generators, or callees do not create target invocations. Compute reaching definitions independently within each invocation, take the set union of observed triples across all invocations, and remove exact duplicate triples only after that union. Definitions never reach from one invocation into another. Include paths that return normally as well as paths on which an exception is raised into or leaves the target frame; only source reads and bindings that actually execute before termination contribute.

Line numbers are absolute, 1-based physical lines in the named repository file as it exists in the repository. Attribute a def or use to the physical source line containing that binding or read. For a multi-line statement or expression, execution begins at its first executable line, but each reported identifier is attributed to the physical line on which that identifier occurs; a continuation line contributes only if its expression actually executes. The target has no decorators, and its `def` line can appear only for a tracked parameter binding; comment and docstring lines cannot create defs or uses.

Return exactly one JSON object with the shape `{"observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]}`. In the actual answer, each `def_line` and `use_line` is a JSON integer and `variable` is the exact source identifier as a JSON string. Sort the list first by `variable` in ascending lexicographic Unicode code-point order, then by `def_line` numerically ascending, then by `use_line` numerically ascending; these fields are the complete tie-break order. No values, function or callee names, invocation numbers, exception type names, or messages are reported, so `repr()` versus `str()`, name-prefix, exception-name, and empty-versus-null conventions do not otherwise apply."""


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
            and node.name == "_run_phased_training"
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
    line_counts = Counter()

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
            raise RuntimeError("target event occurred outside an active invocation")

        if event == "line":
            line_counts[line] += 1
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
    if invocations < 15:
        raise RuntimeError(f"expected at least 15 target invocations, found {invocations}")
    if active:
        raise RuntimeError("final target invocation has no return event")
    if sum(line_counts.values()) < 60:
        raise RuntimeError("target trace contains fewer than 60 line events")
    if len(line_counts) < 8:
        raise RuntimeError("target trace contains fewer than 8 distinct executed lines")
    if len(pairs) < 10:
        raise RuntimeError(f"expected at least 10 def-use pairs, found {len(pairs)}")

    reaching_defs = defaultdict(set)
    for variable, pair_def, pair_use in pairs:
        reaching_defs[(variable, pair_use)].add(pair_def)
    if not any(len(pair_defs) > 1 for pair_defs in reaching_defs.values()):
        raise RuntimeError("no use was reached by different defs across observed paths")

    return [
        {"def_line": pair_def, "use_line": pair_use, "variable": variable}
        for variable, pair_def, pair_use in sorted(pairs)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    oracle = {
        "question_kind": "M4_DataFlow",
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
