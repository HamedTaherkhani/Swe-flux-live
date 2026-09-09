#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


QUESTION = """Run the single pytest test `click_qa/compat_open_stream_s4_dataflow/files/testcase.py::TestOpenStreamDataFlow::test_generated_stream_matrix_and_atomic_retries`. Across all invocations made during that test, what are all unique observed dynamic def-use pairs in the own Python frame of `click._compat.open_stream`, defined in `src/click/_compat.py`, for exactly these local variables: `af`, `atomic`, `binary`, `e`, `encoding`, `errors`, `f`, `fd`, `filename`, `flags`, `mode`, `perm`, and `tmp_filename`?

A definition (“def”) is a successful assignment or binding of one of those names during an invocation. Each parameter is defined at the function's `def` line when that invocation starts. Assignment targets, annotated assignment targets, exception-handler targets, and loop targets are definitions. A definition only occurs if its assignment or binding completes; for example, a target of an assignment whose right-hand side raises is not defined. A use is a runtime read, by a Python `Name` expression in `Load` context, of the tracked name's current value on an executed source line in `open_stream`'s own frame. Exclude reads and bindings performed in nested function, lambda, generator-expression, or comprehension frames, even when their source text is lexically inside `open_stream`; comprehension-local variables are scoped to that nested comprehension frame and are therefore excluded. Uses of captured outer variables from such frames are excluded as well.

Every augmented assignment, such as `x += value` or `x |= value`, is a use of the definition of the old `x` followed by a new definition of `x` on that same line. For `for x in iterable`, each successful binding at the loop header is a new definition of `x` for that iteration; reads used to evaluate `iterable` occur before that binding. Ordinary assignment reads occur before their targets are defined. A pair is `{“variable”: name, “def_line”: D, “use_line”: U}` when the value from the tracked name's most recent completed definition at absolute source line D is read at absolute source line U before another completed definition of that name in the same invocation.

Line numbers are absolute, 1-based physical line numbers in `src/click/_compat.py` as it exists in the repository. The function `def` line, but not decorator or docstring lines, can appear as a parameter definition line. On a multi-line statement or expression, use the physical line containing the relevant read or assignment target; a multi-line assignment's definition takes effect only after the full assignment completes.

Aggregate pairs over every `open_stream` invocation caused by the named test. An invocation is one Python call of `open_stream`, numbered conceptually in chronological order starting at 1, but invocation numbers are not emitted. Remove duplicate triples globally, including repeats within loops and across invocations. Return exactly `{"observed_def_use_pairs": [{"def_line": int, "use_line": int, "variable": str}, ...]}` with no additional keys. All line values are JSON integers and variable names are JSON strings; no values use `repr`, aliases, null, or omitted substitutes. Sort the entries by `variable`, then `def_line`, then `use_line`, all ascending; variable ordering is ordinary Unicode code-point ordering."""

SOURCE_REL = Path("src/click/_compat.py")
TARGET_FUNC = "click._compat.open_stream"
TRACKED = {
    "af",
    "atomic",
    "binary",
    "e",
    "encoding",
    "errors",
    "f",
    "fd",
    "filename",
    "flags",
    "mode",
    "perm",
    "tmp_filename",
}
TRACE_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


class DefUseCollector(ast.NodeVisitor):
    def __init__(self):
        self.uses = {}
        self.definitions = {}
        self._definition_span = None

    def add_definition(self, name, line, end_line):
        if name in TRACKED:
            spans = self.definitions.setdefault(line, [])
            spans.append((end_line, name))

    def visit_Name(self, node):
        if node.id not in TRACKED:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, ast.Store) and self._definition_span is not None:
            start, end = self._definition_span
            self.add_definition(node.id, node.lineno, end)

    def visit_simple_statement(self, node):
        previous = self._definition_span
        self._definition_span = (node.lineno, node.end_lineno)
        self.generic_visit(node)
        self._definition_span = previous

    visit_Assign = visit_simple_statement
    visit_AnnAssign = visit_simple_statement
    visit_NamedExpr = visit_simple_statement

    def visit_AugAssign(self, node):
        if isinstance(node.target, ast.Name) and node.target.id in TRACKED:
            self.uses.setdefault(node.target.lineno, set()).add(node.target.id)
        self.visit_simple_statement(node)

    def visit_For(self, node):
        self.visit(node.iter)
        previous = self._definition_span
        self._definition_span = (node.lineno, node.lineno)
        self.visit(node.target)
        self._definition_span = previous
        for statement in node.body + node.orelse:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_ExceptHandler(self, node):
        if node.type is not None:
            self.visit(node.type)
        if node.name is not None:
            self.add_definition(node.name, node.lineno, node.lineno)
        for statement in node.body:
            self.visit(statement)

    def visit_FunctionDef(self, node):
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    visit_ListComp = visit_FunctionDef
    visit_SetComp = visit_FunctionDef
    visit_DictComp = visit_FunctionDef
    visit_GeneratorExp = visit_FunctionDef


def source_model(source_path):
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")
    except SyntaxError as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "open_stream"
    ]
    if len(functions) != 1:
        fail("expected exactly one top-level function named open_stream")
    function = functions[0]

    collector = DefUseCollector()
    for statement in function.body:
        collector.visit(statement)

    parameters = {
        argument.arg
        for argument in (
            function.args.posonlyargs + function.args.args + function.args.kwonlyargs
        )
        if argument.arg in TRACKED
    }
    if function.args.vararg and function.args.vararg.arg in TRACKED:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg and function.args.kwarg.arg in TRACKED:
        parameters.add(function.args.kwarg.arg)
    return function.lineno, parameters, collector.uses, collector.definitions


def parse_trace(trace_path, model):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    try:
        text = trace_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read trace log {trace_path}: {exc}")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    def_line, parameters, uses, definitions = model
    target_events = []
    for raw_line in text.splitlines():
        match = TRACE_RE.search(raw_line)
        if match is not None and match.group("func") == TARGET_FUNC:
            target_events.append((match.group("event"), int(match.group("line"))))
    if not target_events:
        fail(f"trace log contains zero events for target {TARGET_FUNC}")
    if not any(event == "call" for event, _ in target_events):
        fail(f"trace log contains no call events for target {TARGET_FUNC}")

    pairs = set()
    current = None
    pending = []

    for event, line in target_events:
        if event == "call":
            if current is not None:
                fail("encountered nested open_stream call in a single target event stream")
            current = {name: def_line for name in parameters}
            pending = []
            continue
        if current is None:
            fail(f"encountered target {event} event outside an invocation")

        if event == "exception":
            pending = [
                item for item in pending if not (item[0] <= line <= item[1])
            ]
            continue

        if event == "line":
            remaining = []
            for start, end, def_source_line, name in pending:
                if start <= line <= end:
                    remaining.append((start, end, def_source_line, name))
                else:
                    current[name] = def_source_line
            pending = remaining

            for name in uses.get(line, ()):
                if name not in current:
                    fail(f"use of tracked variable {name!r} at line {line} has no definition")
                pairs.add((name, current[name], line))

            for end, name in definitions.get(line, ()):
                pending.append((line, end, line, name))
            continue

        if event == "return":
            current = None
            pending = []

    if current is not None:
        fail("trace ended before the final open_stream invocation returned")
    if not pairs:
        fail("target events produced no observed def-use pairs")
    return pairs


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    model = source_model(Path.cwd() / SOURCE_REL)
    pairs = parse_trace(Path(args.trace_log), model)
    observed = [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]
    document = {
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
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: unexpected parser failure: {exc}", file=sys.stderr)
        raise
