#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


TARGET_FILE = "kedro/framework/context/catalog_mixins.py"
TARGET_FUNC = "kedro.framework.context.catalog_mixins.describe_datasets"
TRACKED_VARIABLES = (
    "catalog_ds",
    "default_ds",
    "default_ds_by_type",
    "ds_name",
    "i",
    "patterns_ds",
    "patterns_ds_by_type",
    "pipe",
    "pipe_name",
    "pipeline_ds",
    "pipelines",
    "pl_obj",
    "result",
    "target_pipelines",
    "used_ds_by_type",
)
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


class DefUseVisitor(ast.NodeVisitor):
    """Collect lexical Name loads/stores, excluding comprehension execution."""

    def __init__(self):
        self.defs = defaultdict(set)
        self.uses = defaultdict(set)

    def visit_Name(self, node):
        if node.id in TRACKED_VARIABLES:
            if isinstance(node.ctx, ast.Load):
                self.uses[node.lineno].add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                self.defs[node.lineno].add(node.id)

    def visit_ListComp(self, node):
        return

    def visit_SetComp(self, node):
        return

    def visit_DictComp(self, node):
        return

    def visit_GeneratorExp(self, node):
        return


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def find_target_function(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "describe_datasets" and node.lineno == 80:
                return node
    fail(f"target function was not found in {TARGET_FILE}")


def parse_events(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue
        events.append((match.group("event"), int(match.group("line"))))
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event == "call" for event, _ in events):
        fail(f"trace contains no call event for {TARGET_FUNC}")
    return events


def compute_pairs(events, function_node):
    visitor = DefUseVisitor()
    visitor.visit(function_node)

    parameter_names = {
        argument.arg
        for argument in (
            function_node.args.posonlyargs
            + function_node.args.args
            + function_node.args.kwonlyargs
        )
        if argument.arg in TRACKED_VARIABLES
    }
    observed = set()
    reaching_defs = None

    for event, line in events:
        if event == "call":
            reaching_defs = {
                variable: function_node.lineno for variable in parameter_names
            }
            continue
        if event == "return":
            reaching_defs = None
            continue
        if event != "line" or reaching_defs is None:
            continue

        for variable in visitor.uses.get(line, ()):
            if variable in reaching_defs:
                observed.add((variable, reaching_defs[variable], line))
        for variable in visitor.defs.get(line, ()):
            reaching_defs[variable] = line

    if not observed:
        fail("no observed def-use pairs were computed")
    return [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(observed)
    ]


def build_question():
    variables = ", ".join(f"`{name}`" for name in TRACKED_VARIABLES)
    return (
        "Run the pytest test "
        "`kedro_qa/catalog_mixins_describe_datasets_s4_dataflow/files/"
        "testcase.py::TestDescribeDatasetsDataFlow::"
        "test_seeded_mixed_pipeline_descriptions`. During that complete test run, "
        "consider every direct invocation "
        "of `kedro.framework.context.catalog_mixins.CatalogCommandsMixin."
        "describe_datasets` in `kedro/framework/context/catalog_mixins.py`. What are "
        "all unique observed dynamic def-use pairs for exactly these local variables: "
        f"{variables}?\n\n"
        "An invocation is one call of the target function; invocations are numbered "
        "1-based in chronological call order, although invocation numbers are not "
        "included in the aggregate output.\n\n"
        "A def is a binding of a local variable by parameter binding, assignment, or "
        "a `for` target. Parameters count as defined on the function's `def` line. A "
        "use is a runtime read of that local variable. A pair is observed when the "
        "value from that def reaches that use in the same invocation without an "
        "intervening def of the variable. Process reads on a source line before writes "
        "on that same line. Augmented assignment such as `total += delta` first uses "
        "the old reaching def of `total` and then creates a new def of `total` on that "
        "line. Each successfully bound `for` target is a new def on the loop-header "
        "line for that iteration; evaluating the iterable is a use, but a final failed "
        "attempt to obtain another item creates no def. Ignore comprehension-local "
        "variables and all reads and writes performed in comprehension frames, "
        "including reads there of variables captured from the containing function.\n\n"
        "Only execution in the direct `describe_datasets` frame counts; exclude nested "
        "comprehension frames and all callees. Aggregate across all invocations and "
        "remove duplicate triples. Line numbers are absolute 1-based lines in the "
        "named repository file. Attribute a def to the line containing its assignment "
        "target (the `def` line for parameters), and a use to the line containing the "
        "read Name token; thus, for a multi-line statement or expression, use the "
        "specific source line on which that target or Name token begins. Decorator and "
        "docstring lines do not count unless one of the specified runtime bindings or "
        "reads occurs there.\n\n"
        "Return exactly one JSON object with key `observed_def_use_pairs`. Its value "
        "must be a JSON list of objects, each having exactly `def_line` (JSON integer), "
        "`use_line` (JSON integer), and `variable` (the exact source identifier as a "
        "JSON string). Sort ascending by `variable`, then `def_line`, then `use_line`; "
        "after deduplication these keys are a total order. Do not report values or "
        "representations of runtime objects, and use no null or omitted fields."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    events = parse_events(trace_path)
    root = Path(__file__).resolve().parents[3]
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")
    function_node = find_target_function(source_path.read_text(encoding="utf-8"))
    pairs = compute_pairs(events, function_node)

    payload = {
        "question_kind": "S4_DataFlow",
        "question": build_question(),
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {output_path} with {len(pairs)} observed def-use pairs")


if __name__ == "__main__":
    try:
        main()
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
