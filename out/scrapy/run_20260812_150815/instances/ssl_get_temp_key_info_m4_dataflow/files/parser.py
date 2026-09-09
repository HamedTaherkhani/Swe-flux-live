#!/usr/bin/env python3
import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/utils/ssl.py"
TARGET_FUNC = "scrapy.utils.ssl._get_temp_key_info"
TRACKED = {
    "cname",
    "ec_key",
    "key_info",
    "key_type",
    "nid",
    "ssl_object",
    "temp_key",
    "temp_key_p",
}

QUESTION = """Run the pytest class selection `scrapy_qa/ssl_get_temp_key_info_m4_dataflow/files/testcase.py::TestTempKeyInfoDataFlow`. It consists of all twelve `test_...` methods in that class, from `test_01_rotating_prime` through `test_12_final_rotation`, executed in ascending pytest-id/Unicode string order. Across all executions caused by all test methods in that class, what runtime-observed def-use pairs and observation counts occur in `scrapy.utils.ssl._get_temp_key_info` in `scrapy/utils/ssl.py` for exactly these target-frame locals: `cname`, `ec_key`, `key_info`, `key_type`, `nid`, `ssl_object`, `temp_key`, and `temp_key_p`?

A definition (“def”) is a successful binding of one of those locals by parameter binding, assignment, tuple unpacking, a successful `for`-target binding, or a comprehension target when that target belongs to the target function's own frame. The parameter `ssl_object` is defined at the function's `def` line on entry to every invocation. A use is one syntactic `ast.Name` node for a tracked local in `Load` context whose source expression is evaluated in that same target frame while the current definition reaches it, before any later definition of that local. Each evaluated `Name` node is a separate use, so two evaluated Load nodes for the same variable on one line contribute two observations. Reads on an assignment's right-hand side occur before its new bindings. Attribute assignment such as `obj.field = value` uses `obj` but does not redefine it. An augmented assignment such as `item += 1` first uses the old `item` definition and then defines `item` on that same line.

For a loop header `for item in values`, evaluating `values` uses its tracked names normally, and every successful iteration that enters the body defines `item` on the loop-header line; an exhausted check that does not enter the body creates neither that binding nor another use of `values`. Iteration N means the Nth successful execution that proceeds from a given loop header into its body, counted separately per target invocation. Comprehension and generator-expression bodies execute in their implicit frames: their local targets and body reads are excluded from this target-frame analysis, while the outermost iterable expression evaluated in the target frame is included normally. (The assigned target currently contains no loop or comprehension; these rules fix the conventions without creating observations.)

An invocation is one `call` event entering `_get_temp_key_info`, numbered 1-based in chronological order across the ordered test methods. Only executed source expressions in that invocation's target frame contribute uses; calls in callees, caller frames, builtins, or any other frame are excluded. `call`, `return`, and `exception` events do not themselves create uses or definitions beyond the parameter definitions on entry. For every use observation, form `(variable, def_line, use_line)` from the definition that reaches it and increment that exact triple's `count` by one. A repeatedly evaluated use contributes once per evaluated Name occurrence. Counts are totals summed across every invocation in every test method in the class. Omit triples with zero observations. Emit each distinct triple exactly once—the `count` carries all multiplicity—and sort rows by `variable` in ascending Unicode string order, then by `def_line` numerically ascending, then by `use_line` numerically ascending. There are no further ties because the triple is unique.

Line numbers are absolute, 1-based physical source lines in `scrapy/utils/ssl.py` as it exists in the repository. For a multi-line statement or expression, use the line of the relevant AST `Name` node—the physical line where that particular read or binding begins—rather than necessarily the statement's first line. Parameters use the function `def` line. Decorator and docstring lines do not count unless they contain an evaluated tracked-local read in the target frame; calling the function alone does not make the `def` line a use.

Return exactly one JSON object with key `observed_def_use_pairs`. Its value is a JSON array whose elements each have exactly `count` (JSON integer), `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Variable names are emitted directly as the enumerated strings and numbers directly as JSON integers: no `repr()` or `str()` formatting is applied, and no null, empty-string, or omitted-value sentinel is used."""


class LocalFlow(ast.NodeVisitor):
    def __init__(self):
        self.defs = defaultdict(Counter)
        self.uses = defaultdict(Counter)

    def visit_Name(self, node):
        if node.id in TRACKED:
            destination = self.uses if isinstance(node.ctx, ast.Load) else self.defs
            destination[node.lineno][node.id] += 1

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
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_get_temp_key_info"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    flow = LocalFlow()
    for statement in target.body:
        flow.visit(statement)
    parameters = {
        arg.arg
        for arg in (
            list(target.args.posonlyargs)
            + list(target.args.args)
            + list(target.args.kwonlyargs)
        )
        if arg.arg in TRACKED
    }
    return target.lineno, parameters, dict(flow.defs), dict(flow.uses)


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
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.search(raw_line)
        if match and match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            events.append((match.group("event"), int(match.group("line"))))

    if not events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not any(event == "call" and line == def_line for event, line in events):
        raise RuntimeError(f"trace contains no entry call for {TARGET_FUNC}")
    if not any(event == "line" for event, _line in events):
        raise RuntimeError(f"trace contains no executed lines for {TARGET_FUNC}")

    counts = Counter()
    reaching_defs = None
    invocation_count = 0
    completed_count = 0
    for event, line in events:
        if event == "call":
            if reaching_defs is not None:
                raise RuntimeError("overlapping target invocations are unsupported")
            invocation_count += 1
            reaching_defs = {name: def_line for name in parameters}
            continue
        if event == "return":
            if reaching_defs is None:
                raise RuntimeError(f"return outside a target invocation at line {line}")
            completed_count += 1
            reaching_defs = None
            continue
        if event != "line":
            continue
        if reaching_defs is None:
            raise RuntimeError(f"line event outside a target invocation at line {line}")

        for variable, multiplicity in uses_by_line.get(line, {}).items():
            if variable in reaching_defs:
                counts[(variable, reaching_defs[variable], line)] += multiplicity
        for variable in defs_by_line.get(line, {}):
            reaching_defs[variable] = line

    if reaching_defs is not None:
        raise RuntimeError("target invocation did not finish")
    if invocation_count == 0 or completed_count != invocation_count:
        raise RuntimeError(
            f"incomplete invocation accounting: {invocation_count} entered, "
            f"{completed_count} returned"
        )
    if not counts:
        raise RuntimeError("computed def-use answer is unexpectedly empty")

    return {
        "observed_def_use_pairs": [
            {
                "count": count,
                "def_line": definition,
                "use_line": use,
                "variable": variable,
            }
            for (variable, definition, use), count in sorted(counts.items())
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {
                    "count": "int",
                    "def_line": "int",
                    "use_line": "int",
                    "variable": "str",
                }
            ]
        },
        "oracle_answer": parse_trace(args.trace_log, source_path),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
