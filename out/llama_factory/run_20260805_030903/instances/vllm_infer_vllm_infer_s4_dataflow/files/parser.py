#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scripts/vllm_infer.py"
TARGET_FUNCTION = "vllm_infer"
TRACKED_VARIABLES = (
    "engine_args",
    "inputs",
    "label",
    "labels",
    "lora_request",
    "multi_modal_data",
    "pred",
    "preds",
    "prompts",
    "sample",
    "sampling_params",
    "text",
)

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/vllm_infer_vllm_infer_s4_dataflow/files/testcase.py::"
    "TestVllmInferDataFlow::test_seeded_cli_entrypoint_multimodal_batches`. Across every invocation "
    "of `scripts.vllm_infer.vllm_infer` in `scripts/vllm_infer.py`, report all unique observed "
    "dynamic def-use pairs for exactly these local variables: `engine_args`, `inputs`, `label`, "
    "`labels`, `lora_request`, `multi_modal_data`, `pred`, `preds`, `prompts`, `sample`, "
    "`sampling_params`, and `text`. An invocation is one runtime entry into that exact function; "
    "invocations are numbered 1-based in chronological order over the complete test run, and pairs "
    "from all invocations are combined before deduplication. A definition (`def`) is a binding of "
    "the local name by parameter binding or an executed assignment target. Each parameter is "
    "defined at the function's `def` line on every invocation, regardless of the physical line on "
    "which that parameter is displayed. A use is a runtime evaluation of that local name in load "
    "context. A def-use pair exists when a use reads the binding produced by that def and no "
    "executed redefinition of the same local occurred between them in that invocation. For an "
    "ordinary assignment whose right-hand side uses the same name, the right-hand-side use reads "
    "the prior def and the assignment then creates the new def. Augmented assignment such as "
    "`counter += delta` first uses the old binding and then creates a new definition on that same "
    "line, so it is both a use of the reaching def and a new def. A `for` loop header redefines its "
    "target on each successful iteration before the body executes; an unsuccessful exhaustion "
    "check does not define the target. Names bound locally by a list, set, or dict comprehension or "
    "generator expression are scoped to that comprehension and are excluded as defs and uses; "
    "reads of tracked outer locals in a comprehension's iterable or other expressions still count. "
    "Attribute or subscript writes and mutating method calls do not rebind the base local name; "
    "evaluating that base name is a use. Line numbers are absolute, 1-based source line numbers in "
    "the named repository file. The parameter definitions use the line where the function's `def` "
    "statement begins. Otherwise, for a multi-line statement or expression, a def or use is "
    "attributed to the physical source line on which the relevant assignment target or loaded name "
    "begins; decorator and docstring lines do not count. Remove duplicate triples after combining "
    "all invocations, including duplicates caused by repeated loop iterations or multiple reads of "
    "the same reaching def on one line. Return exactly one JSON object with key "
    "`observed_def_use_pairs`; its value is a JSON array of objects, each having exactly `def_line` "
    "(JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Sort the array by "
    "`variable`, then `def_line`, then `use_line`, all ascending by ordinary string order for "
    "`variable` and numeric order for the line numbers. No other value serialization, null "
    "representation, function-name formatting, exception-name formatting, counting, or tie-breaker "
    "convention applies to this answer."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*scripts/vllm_infer\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def bound_names(node):
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names = set()
        for element in node.elts:
            names.update(bound_names(element))
        return names
    return set()


class DefUseVisitor(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = set(tracked)
        self.defs = {name: set() for name in tracked}
        self.uses = {name: set() for name in tracked}
        self.comprehension_locals = set()

    def visit_Name(self, node):
        if node.id not in self.tracked or node.id in self.comprehension_locals:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses[node.id].add(node.lineno)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defs[node.id].add(node.lineno)

    def visit_AugAssign(self, node):
        if (
            isinstance(node.target, ast.Name)
            and node.target.id in self.tracked
            and node.target.id not in self.comprehension_locals
        ):
            self.uses[node.target.id].add(node.target.lineno)
            self.defs[node.target.id].add(node.target.lineno)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def visit_ListComp(self, node):
        self.visit_comprehension(node, (node.elt,))

    def visit_SetComp(self, node):
        self.visit_comprehension(node, (node.elt,))

    def visit_GeneratorExp(self, node):
        self.visit_comprehension(node, (node.elt,))

    def visit_DictComp(self, node):
        self.visit_comprehension(node, (node.key, node.value))

    def visit_comprehension(self, node, result_nodes):
        previous = set(self.comprehension_locals)
        for generator in node.generators:
            self.visit(generator.iter)
            self.comprehension_locals.update(bound_names(generator.target))
            for condition in generator.ifs:
                self.visit(condition)
        for result_node in result_nodes:
            self.visit(result_node)
        self.comprehension_locals = previous


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def find_target_function(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_FUNCTION:
            return node
    fail(f"cannot find {TARGET_FUNCTION} in {TARGET_FILE}")


def source_def_use(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = find_target_function(tree)
    visitor = DefUseVisitor(TRACKED_VARIABLES)
    for statement in target.body:
        visitor.visit(statement)

    parameters = {
        argument.arg
        for argument in (
            list(target.args.posonlyargs)
            + list(target.args.args)
            + list(target.args.kwonlyargs)
        )
    }
    if target.args.vararg is not None:
        parameters.add(target.args.vararg.arg)
    if target.args.kwarg is not None:
        parameters.add(target.args.kwarg.arg)
    for name in TRACKED_VARIABLES:
        if name in parameters:
            visitor.defs[name].add(target.lineno)

    return target.lineno, visitor.defs, visitor.uses


def read_target_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func").endswith(f".{TARGET_FUNCTION}"):
            events.append((match.group("event"), int(match.group("line"))))
    return events


def compute_pairs(events, function_line, defs_by_name, uses_by_name):
    pairs = set()
    reaching = None
    invocation_count = 0

    for event, line in events:
        if event == "call":
            if reaching is not None:
                fail("encountered a nested target call before the prior invocation returned")
            invocation_count += 1
            reaching = {
                name: function_line if function_line in defs_by_name[name] else None
                for name in TRACKED_VARIABLES
            }
            continue

        if reaching is None:
            continue
        if event == "return":
            reaching = None
            continue
        if event != "line":
            continue

        for name in TRACKED_VARIABLES:
            if line in uses_by_name[name]:
                reaching_definition = reaching[name]
                if reaching_definition is None:
                    fail(f"observed use of {name!r} at line {line} without a reaching definition")
                pairs.add((name, reaching_definition, line))

        for name in TRACKED_VARIABLES:
            if line in defs_by_name[name]:
                reaching[name] = line

    if invocation_count == 0:
        fail(f"trace contains zero call events for {TARGET_FUNCTION}")
    if reaching is not None:
        fail(f"final invocation of {TARGET_FUNCTION} has no return event")
    if not pairs:
        fail("computed zero observed def-use pairs")

    return [
        {"def_line": definition, "use_line": use, "variable": variable}
        for variable, definition, use in sorted(pairs)
    ]


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    repo_root = Path(__file__).resolve().parents[3]
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")

    function_line, defs_by_name, uses_by_name = source_def_use(source_path)
    events = read_target_events(trace_path)
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNCTION}")
    observed_pairs = compute_pairs(events, function_line, defs_by_name, uses_by_name)

    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": observed_pairs},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
