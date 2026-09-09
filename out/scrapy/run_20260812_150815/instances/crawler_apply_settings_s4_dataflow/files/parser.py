#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scrapy/crawler.py"
TARGET_FUNC = "scrapy.crawler.Crawler._apply_settings"
TRACKED = {
    "d",
    "event_loop",
    "lf_cls",
    "reactor_class",
    "self",
    "use_reactor",
}

QUESTION = """Run the single pytest test `scrapy_qa/crawler_apply_settings_s4_dataflow/files/testcase.py::TestCrawlerSettingsDataFlow::test_runner_settings_paths`. Across all invocations made by that test of `scrapy.crawler.Crawler._apply_settings` in `scrapy/crawler.py`, what unique runtime-observed def-use pairs occur for exactly these local variables: `d`, `event_loop`, `lf_cls`, `reactor_class`, `self`, and `use_reactor`?

A definition (“def”) is a successful binding of a local by parameter binding or assignment in the target frame. Parameters count as defined on the function's `def` line. A use is a read (`Load` context in Python's AST) of that local on an executed source line while the current definition still reaches it, before any later definition of that local. Attribute assignment such as `obj.field = value` reads `obj` but does not redefine `obj`. For an assignment, reads of the right-hand side happen before the new definition. An augmented assignment such as `item += 1` both uses the old reaching definition and creates a new definition on that same line. A `for item in values` loop header reads `values` and redefines `item` on every executed iteration. Comprehension-local targets belong to the comprehension's implicit frame, not the target function's frame, and are excluded; reads evaluated in the target frame still count.

Aggregate pairs across every target invocation in the test, remove duplicate `{variable, def_line, use_line}` triples even when observed repeatedly, and sort the result by `variable` (ascending Unicode string order), then `def_line`, then `use_line`, both numerically ascending. Line numbers are absolute 1-based source line numbers in `scrapy/crawler.py` as it exists in the repository. For a multi-line statement or expression, use the line attached to the relevant variable's AST `Name` node—the physical line on which that variable read or binding begins. Decorator and docstring lines do not count unless they contain an executed read in the target frame; the function's `def` line may appear as a parameter definition but not as a use merely because the function was called.

Return exactly one JSON object with key `observed_def_use_pairs`. Its value is a JSON array of objects, each with exactly `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). No `repr()` or `str()` conversion is applied: variable names are emitted directly as JSON strings and line numbers directly as JSON integers."""


class LocalFlow(ast.NodeVisitor):
    def __init__(self):
        self.defs = {}
        self.uses = {}

    def visit_Name(self, node):
        if node.id in TRACKED:
            destination = self.uses if isinstance(node.ctx, ast.Load) else self.defs
            destination.setdefault(node.lineno, set()).add(node.id)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_ClassDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def _visit_comprehension(self, node):
        if node.generators:
            self.visit(node.generators[0].iter)

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension


def target_flow(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Crawler":
            target = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, ast.FunctionDef)
                    and child.name == "_apply_settings"
                ),
                None,
            )
            break
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    flow = LocalFlow()
    for statement in target.body:
        flow.visit(statement)

    parameter_names = {
        arg.arg
        for arg in (
            list(target.args.posonlyargs)
            + list(target.args.args)
            + list(target.args.kwonlyargs)
        )
        if arg.arg in TRACKED
    }
    return target.lineno, parameter_names, flow.defs, flow.uses


TRACE_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    + re.escape(TARGET_FUNC)
    + r"\s+event=(?P<event>call|line|return|exception)\b"
)


def parse_trace(trace_path, source_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    def_line, parameters, defs_by_line, uses_by_line = target_flow(source_path)
    target_events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.search(raw_line)
        if match and match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            target_events.append((match.group("event"), int(match.group("line"))))

    if not target_events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not any(event == "call" for event, _ in target_events):
        raise RuntimeError(f"trace contains no call event for {TARGET_FUNC}")
    if not any(event == "line" for event, _ in target_events):
        raise RuntimeError(f"trace contains no executed lines for {TARGET_FUNC}")

    pairs = set()
    reaching_defs = None
    invocation_count = 0
    for event, line in target_events:
        if event == "call":
            if reaching_defs is not None:
                raise RuntimeError("overlapping target invocations are unsupported")
            invocation_count += 1
            reaching_defs = {name: def_line for name in parameters}
            continue
        if event == "return":
            reaching_defs = None
            continue
        if event != "line":
            continue
        if reaching_defs is None:
            raise RuntimeError(f"line event outside a target invocation at line {line}")

        for variable in uses_by_line.get(line, ()):
            if variable in reaching_defs:
                pairs.add((variable, reaching_defs[variable], line))
        for variable in defs_by_line.get(line, ()):
            reaching_defs[variable] = line

    if invocation_count == 0:
        raise RuntimeError(f"no completed invocation accounting for {TARGET_FUNC}")
    if not pairs:
        raise RuntimeError("computed def-use answer is unexpectedly empty")

    return {
        "observed_def_use_pairs": [
            {"def_line": def_line, "use_line": use_line, "variable": variable}
            for variable, def_line, use_line in sorted(pairs)
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    oracle_answer = parse_trace(args.trace_log, source_path)
    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
