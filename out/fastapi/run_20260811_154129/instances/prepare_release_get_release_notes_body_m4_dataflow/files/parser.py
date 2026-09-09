#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/prepare_release.py"
TARGET_QUALNAME = "scripts.prepare_release.get_release_notes_body"
TRACKED_VARIABLES = (
    "body",
    "content",
    "end",
    "match",
    "next_match",
    "release_notes_file",
    "version",
    "version_heading",
)
PARAMETERS = {"content", "version", "release_notes_file"}

QUESTION = """Run the pytest test `fastapi_qa/prepare_release_get_release_notes_body_m4_dataflow/files/testcase.py::TestReleaseNotesBodyDataFlow::test_generated_release_note_layouts`. During that complete test run, consider every invocation of `scripts.prepare_release.get_release_notes_body` in `scripts/prepare_release.py`, including invocations that terminate by raising an exception. An invocation is one chronological entry into that function (one function call); invocation numbering, if needed when reproducing the run, is 1-based in entry order. What are all unique observed def-use pairs, unioned across those invocations, for exactly these local variables: `body`, `content`, `end`, `match`, `next_match`, `release_notes_file`, `version`, and `version_heading`?

A "def" is a binding performed by an executed plain assignment, parameter binding, augmented assignment, or loop-target binding in the target function's own frame. Each parameter is defined on the function's `def` line separately for every invocation. A "use" is an executed read of that local variable in the target function's own frame. A pair is observed when a definition reaches such a read in the same invocation without another executed definition of that variable in between. On a line containing both reads and bindings, reads occur before the new bindings for this analysis. Thus an augmented assignment such as `total += item` uses the reaching definition of `total` and then defines `total` on that line; a loop header such as `for item in values` uses `values` and defines `item` on the header line each time that header binds an item. Comprehension-local variables and executions in comprehension frames are excluded; parameters used by a comprehension would count only if the read executes in the target function's own frame.

Only source operations on lines that actually execute in each target-function invocation count; operations skipped because of a branch or an earlier exception do not count. A raised exception ends that invocation after any reads and definitions already executed. Report absolute 1-based source line numbers in the named repository file. For a multi-line statement or expression, attribute a definition or use to the physical line where its binding target or read expression begins, including a continuation line when the relevant expression begins there. The function `def` line can appear only for parameter definitions; decorator and docstring lines do not count unless they execute a tracked-variable read or definition under these rules.

Remove duplicate `(variable, def_line, use_line)` triples after taking the union across all invocations. Return exactly one JSON object with the key `observed_def_use_pairs`; its value is a list of objects, each having exactly the keys `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Sort the list by `variable` lexicographically ascending, then `def_line` numerically ascending, then `use_line` numerically ascending. There are no serialized runtime values, exception names, function names, or absent-value sentinels in the answer."""


class LocalAccessVisitor(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = tracked
        self.definitions = {}
        self.uses = {}

    def visit_Name(self, node):
        if node.id not in self.tracked:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.definitions.setdefault(node.lineno, set()).add(node.id)

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
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_release_notes_body"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    visitor = LocalAccessVisitor(set(TRACKED_VARIABLES))
    for statement in target.body:
        visitor.visit(statement)
    return target.lineno, visitor.definitions, visitor.uses


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
    if not any(event == "call" for _, event in events):
        raise RuntimeError(f"trace contains no call events for {TARGET_QUALNAME}")
    if not any(event == "line" for _, event in events):
        raise RuntimeError(f"trace contains no line events for {TARGET_QUALNAME}")
    return events


def compute_pairs(events, def_line, definitions, uses):
    reaching_definitions = None
    pairs = set()

    for line, event in events:
        if event == "call":
            if reaching_definitions is not None:
                raise RuntimeError("overlapping target invocations are unsupported")
            reaching_definitions = {parameter: def_line for parameter in PARAMETERS}
            continue
        if reaching_definitions is None:
            continue
        if event == "return":
            reaching_definitions = None
            continue
        if event != "line":
            continue

        for variable in sorted(uses.get(line, ())):
            definition = reaching_definitions.get(variable)
            if definition is not None:
                pairs.add((variable, definition, line))
        for variable in sorted(definitions.get(line, ())):
            reaching_definitions[variable] = line

    if reaching_definitions is not None:
        raise RuntimeError("trace ended during a target invocation")
    if not pairs:
        raise RuntimeError("target events produced no observed def-use pairs")
    return [
        {"def_line": definition, "use_line": use, "variable": variable}
        for variable, definition, use in sorted(pairs)
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    def_line, definitions, uses = source_accesses(source_path)
    events = parse_events(Path(args.trace_log))
    observed_pairs = compute_pairs(events, def_line, definitions, uses)

    result = {
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
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
