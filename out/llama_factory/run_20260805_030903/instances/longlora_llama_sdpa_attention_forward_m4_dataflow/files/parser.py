#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/model/model_utils/longlora.py"
TARGET_FUNCTION = "llama_sdpa_attention_forward"
TARGET_TRACE_FUNC = (
    "llamafactory.model.model_utils.longlora.llama_sdpa_attention_forward"
)
TRACKED_VARIABLES = (
    "attention_mask",
    "attn_output",
    "cos",
    "groupsz",
    "key_states",
    "num_groups",
    "q_len",
    "query_states",
    "sin",
    "value_states",
)

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/longlora_llama_sdpa_attention_forward_m4_dataflow/files/testcase.py::"
    "TestLongLoraSdpaDataFlow::test_seeded_attention_branch_matrix_through_pipeline`. Across "
    "every invocation of "
    "`llamafactory.model.model_utils.longlora.llama_sdpa_attention_forward` in "
    "`src/llamafactory/model/model_utils/longlora.py`, report all unique observed dynamic "
    "def-use pairs for exactly these local variables: `attention_mask`, `attn_output`, `cos`, "
    "`groupsz`, `key_states`, `num_groups`, `q_len`, `query_states`, `sin`, and "
    "`value_states`. An invocation is one runtime entry into that exact function during the "
    "complete test run; invocations are numbered 1-based in chronological order, although "
    "invocation numbers are not included in the answer. Combine pairs from all invocations "
    "before deduplication. A definition (`def`) is a binding of a tracked local name by "
    "parameter binding or an executed assignment target, including tuple-unpacking targets. "
    "Each tracked parameter is defined at the line where the function's `def` statement begins "
    "on every invocation, regardless of the physical line on which the parameter is displayed. "
    "A use is an executed evaluation of a tracked local name in load context. A def-use pair "
    "exists when a use reads the binding produced by that definition and no executed "
    "redefinition of the same local occurred between them in the same invocation. Process each "
    "executed source line's uses before its definitions: for an ordinary assignment whose "
    "right-hand side uses the same name, the right-hand-side use reads the prior definition and "
    "the assignment then creates the new definition. Augmented assignment such as "
    "`total += increment` first uses the old binding and then creates a new definition on that "
    "same line, so it is both a use of the reaching definition and a new definition. A `for` "
    "loop header redefines its target on each successful iteration before the body executes; an "
    "unsuccessful exhaustion check does not define it. Names bound locally by a list, set, or "
    "dict comprehension or generator expression are scoped to that comprehension and are "
    "excluded as definitions and uses; reads of tracked outer locals in a comprehension's "
    "iterable, filters, or result expressions still count. Attribute and subscript writes and "
    "mutating method calls do not rebind the base local name; evaluating that base name is a "
    "use. Only defs and uses lexically in this function body count; nested named functions and "
    "lambdas are excluded. A source line is observed only when execution of this exact "
    "function's frame reaches that line in an invocation; activity solely in a called or nested "
    "function does not independently make an outer-function line observed. Line numbers are "
    "absolute, 1-based source line numbers in the named repository file. Parameter definitions "
    "use the line where `def` begins. Otherwise, for a multi-line statement or expression, "
    "attribute a def or use to the physical source line on which the relevant assignment target "
    "or loaded name begins; continuation lines count only when execution reaches that physical "
    "line, while decorator, comment, and docstring lines do not count. Remove duplicate triples "
    "after combining all invocations, including duplicates caused by repeated invocations, "
    "repeated executions, or multiple reads of the same reaching definition on one source line. "
    "Return exactly one JSON object with key `observed_def_use_pairs`; its value is a JSON array "
    "of objects, each having exactly `def_line` (JSON integer), `use_line` (JSON integer), and "
    "`variable` (JSON string containing the bare local name). Sort the array by `variable`, then "
    "`def_line`, then `use_line`, all ascending by ordinary Unicode string order for `variable` "
    "and numeric order for line numbers. No value is formatted with `repr()` or `str()`, no null, "
    "empty-string, or absent-value marker is used, and no function-name, exception-name, "
    "iteration-count, or additional tie-breaker convention applies to the answer."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/model/model_utils/longlora\.py):(?P<line>\d+) "
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
    def __init__(self):
        self.tracked = set(TRACKED_VARIABLES)
        self.defs = {name: set() for name in TRACKED_VARIABLES}
        self.uses = {name: set() for name in TRACKED_VARIABLES}
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
        self._visit_comprehension(node, (node.elt,))

    def visit_SetComp(self, node):
        self._visit_comprehension(node, (node.elt,))

    def visit_GeneratorExp(self, node):
        self._visit_comprehension(node, (node.elt,))

    def visit_DictComp(self, node):
        self._visit_comprehension(node, (node.key, node.value))

    def _visit_comprehension(self, node, result_nodes):
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
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_FUNCTION
        ):
            return node
    fail(f"cannot find {TARGET_FUNCTION} in {TARGET_FILE}")


def source_def_use(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = find_target_function(tree)
    visitor = DefUseVisitor()
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
        if match and match.group("func") == TARGET_TRACE_FUNC:
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
                    fail(
                        f"observed use of {name!r} at line {line} without a reaching definition"
                    )
                pairs.add((name, reaching_definition, line))

        for name in TRACKED_VARIABLES:
            if line in defs_by_name[name]:
                reaching[name] = line

    if invocation_count == 0:
        fail(f"trace contains zero call events for {TARGET_TRACE_FUNC}")
    if reaching is not None:
        fail(f"final invocation of {TARGET_TRACE_FUNC} has no return event")
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
        fail(f"trace contains zero events for {TARGET_TRACE_FUNC}")
    observed_pairs = compute_pairs(
        events, function_line, defs_by_name, uses_by_name
    )

    payload = {
        "question_kind": "M4_DataFlow",
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
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
