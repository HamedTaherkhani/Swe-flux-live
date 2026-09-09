#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/chat/vllm_engine.py"
TARGET_TRACE_FUNC = "llamafactory.chat.vllm_engine._generate"
TARGET_CLASS = "VllmEngine"
TARGET_METHOD = "_generate"
TRACKED_VARIABLES = ("max_tokens", "multi_modal_data", "system")

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/vllm_engine_generate_m4_dataflow/files/testcase.py::"
    "TestVllmEngineGenerateDataFlow::test_seeded_branch_matrix_through_chat`. "
    "Across every invocation of `llamafactory.chat.vllm_engine.VllmEngine._generate` in "
    "`src/llamafactory/chat/vllm_engine.py`, report all unique observed dynamic def-use pairs "
    "for exactly these local variables: `max_tokens`, `multi_modal_data`, and `system`. An "
    "invocation is one runtime entry into that exact function during the complete test run; "
    "invocations are numbered 1-based in chronological order, although invocation numbers are "
    "not included in the answer, and pairs from all invocations are combined before "
    "deduplication. A definition (`def`) is a binding of the local name by parameter binding or "
    "an executed assignment target. Each parameter is defined at the line where the function's "
    "`async def` statement begins on every invocation, regardless of the physical line on which "
    "that parameter is displayed. A use is a runtime evaluation of that local name in load "
    "context. A def-use pair exists when a use reads the binding produced by that def and no "
    "executed redefinition of the same local occurred between them in that invocation. Process "
    "each executed source line's uses before its definitions: thus, for an ordinary assignment "
    "whose right-hand side uses the same name, that use reads the prior definition and the "
    "assignment then creates the new definition. Augmented assignment such as `total += item` "
    "first uses the old binding and then creates a new definition on that same line, so it is "
    "both a use of the reaching definition and a new definition. A `for` loop header redefines "
    "its target on each successful iteration before the body executes. Names bound locally by a "
    "list, set, or dict comprehension or generator expression are scoped to that comprehension "
    "and are excluded as definitions and uses; reads of tracked outer locals in a "
    "comprehension's iterable or other expressions still count. Attribute or subscript writes "
    "and mutating method calls do not rebind the base local name; evaluating that base name is a "
    "use. Only defs and uses belonging lexically to this function body count; nested named "
    "functions and lambdas are excluded. A source line is observed when execution of this exact "
    "function reaches that line in an invocation; activity solely inside a called function or a "
    "comprehension's separate runtime frame does not independently add lines. Line numbers are "
    "absolute, 1-based source line numbers in the named repository file. Parameter definitions "
    "use the `async def` line. Otherwise, for a multi-line statement or expression, a def or use "
    "is attributed to the physical source line on which the relevant assignment target or "
    "loaded name begins; decorator and docstring lines do not count. Remove duplicate triples "
    "after combining all invocations, including duplicates caused by repeated invocations or "
    "multiple reads of the same reaching definition on one line. Return exactly one JSON object "
    "with key `observed_def_use_pairs`; its value is a JSON array of objects, each having exactly "
    "`def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Sort the "
    "array by `variable`, then `def_line`, then `use_line`, all ascending by ordinary Unicode "
    "string order for `variable` and numeric order for the line numbers. No values are rendered "
    "with `repr` or `str`, no null or absent-value marker is used, and no function-name, "
    "exception-name, iteration-count, or additional tie-breaker convention applies to the answer."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/chat/vllm_engine\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


class DefUseVisitor(ast.NodeVisitor):
    def __init__(self):
        self.tracked = set(TRACKED_VARIABLES)
        self.defs = {name: set() for name in TRACKED_VARIABLES}
        self.uses = {name: set() for name in TRACKED_VARIABLES}

    def visit_Name(self, node):
        if node.id not in self.tracked:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses[node.id].add(node.lineno)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defs[node.id].add(node.lineno)

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name) and node.target.id in self.tracked:
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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def find_target_function(tree):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for child in node.body:
                if isinstance(child, ast.AsyncFunctionDef) and child.name == TARGET_METHOD:
                    return child
    fail(f"cannot find {TARGET_CLASS}.{TARGET_METHOD} in {TARGET_FILE}")


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
                    fail(f"observed use of {name!r} at line {line} without a reaching definition")
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

    repository_root = Path(__file__).resolve().parents[3]
    source_path = repository_root / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")

    function_line, defs_by_name, uses_by_name = source_def_use(source_path)
    events = read_target_events(trace_path)
    if not events:
        fail(f"trace contains zero events for {TARGET_TRACE_FUNC}")
    observed_pairs = compute_pairs(events, function_line, defs_by_name, uses_by_name)

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
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
