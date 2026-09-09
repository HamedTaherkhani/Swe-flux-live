#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "docs_src/security/tutorial005_an_py310.py"
TARGET_QUALNAME = "docs_src.security.tutorial005_an_py310.get_current_user"
TRACKED_VARIABLES = (
    "authenticate_value",
    "credentials_exception",
    "payload",
    "scope",
    "security_scopes",
    "token",
    "token_data",
    "token_scopes",
    "user",
    "username",
)

QUESTION = """Run the pytest test `fastapi_qa/tutorial005_an_py310_get_current_user_s4_dataflow/files/testcase.py::TestGetCurrentUserDataFlow::test_generated_scope_matrix`. During that complete test run, consider every invocation of `docs_src.security.tutorial005_an_py310.get_current_user` in `docs_src/security/tutorial005_an_py310.py`. What are all unique observed def-use pairs for exactly these local variables: `authenticate_value`, `credentials_exception`, `payload`, `scope`, `security_scopes`, `token`, `token_data`, `token_scopes`, `user`, and `username`?

A "def" is a binding performed by an executed assignment, parameter binding, or loop-target binding in the target function's own frame. Parameters are defined on the function's `def` line for each invocation. A "use" is an executed read of that local variable in the target function's own frame. A pair is observed when the value from a definition is read at a use before that variable is redefined in the same invocation. Reads on an assignment line occur before that line's new definition takes effect. An augmented assignment such as `x += delta` is both a use of the reaching definition of `x` and a new definition of `x` on that same line. A loop header such as `for x in items` reads its iterable and redefines `x` on the header line on every iteration. Comprehension-local bindings and all events in comprehension frames are excluded; they are not definitions or uses in the target function's frame.

Report source line numbers as absolute 1-based line numbers in the named repository file. For a multi-line statement or expression, attribute each definition or use to the physical source line where that variable's binding target or read expression begins; continuation lines therefore count when the relevant expression begins there. The function `def` line can appear only as a parameter definition; decorator and docstring lines do not count unless they execute a tracked-variable read or definition under the rules above.

Remove duplicate triples across all invocations. Return exactly one JSON object with key `observed_def_use_pairs`; its value is a list of objects having exactly the keys `def_line` (integer), `use_line` (integer), and `variable` (string). Sort the list by `variable` lexicographically ascending, then `def_line` numerically ascending, then `use_line` numerically ascending. No runtime values are serialized in this answer."""


class LocalAccessVisitor(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = tracked
        self.defs = {}
        self.uses = {}

    def visit_Name(self, node):
        if node.id not in self.tracked:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defs.setdefault(node.lineno, set()).add(node.id)

    def visit_comprehension(self, node):
        return

    def visit_ListComp(self, node):
        return

    def visit_SetComp(self, node):
        return

    def visit_DictComp(self, node):
        return

    def visit_GeneratorExp(self, node):
        return

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return


def source_accesses(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_current_user"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    visitor = LocalAccessVisitor(set(TRACKED_VARIABLES))
    for statement in target.body:
        visitor.visit(statement)
    return target.lineno, visitor.defs, visitor.uses


def parse_events(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        rf"\S*{re.escape(TARGET_FILE)}:(\d+)\s+"
        rf"{re.escape(TARGET_QUALNAME)}\s+event=(call|line|return|exception)\b"
    )
    events = [(int(match.group(1)), match.group(2)) for match in pattern.finditer(text)]
    if not events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_QUALNAME} in {TARGET_FILE}"
        )
    if not any(event == "line" for _, event in events):
        raise RuntimeError(f"trace contains no line events for {TARGET_QUALNAME}")
    return events


def compute_pairs(events, def_line, definitions, uses):
    parameter_names = {"security_scopes", "token"}
    reaching_defs = None
    pairs = set()

    for line, event in events:
        if event == "call":
            reaching_defs = {name: def_line for name in parameter_names}
            continue
        if reaching_defs is None:
            continue
        if event == "return":
            reaching_defs = None
            continue
        if event != "line":
            continue

        for variable in sorted(uses.get(line, ())):
            reaching = reaching_defs.get(variable)
            if reaching is not None:
                pairs.add((variable, reaching, line))
        for variable in sorted(definitions.get(line, ())):
            reaching_defs[variable] = line

    if not pairs:
        raise RuntimeError("target events produced no observed def-use pairs")
    return [
        {"def_line": defn, "use_line": use, "variable": variable}
        for variable, defn, use in sorted(pairs)
    ]


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    def_line, definitions, uses = source_accesses(source_path)
    events = parse_events(Path(args.trace_log))
    observed_pairs = compute_pairs(events, def_line, definitions, uses)

    result = {
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
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
