import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = Path("haystack/components/websearch/serper_dev.py")
TARGET_FUNC = "haystack.components.websearch.serper_dev.run"
TRACKED = ("answer_box_content", "answer_dict", "highlighted_answers", "result", "title")

QUESTION = """Run the single pytest test `haystack_qa/serper_dev_run_s4_dataflow/files/testcase.py::TestSerperDevRunDataFlow::test_generated_response_variants`. Across all invocations made by that test, report the unique runtime-observed def-use pairs for the local variables `answer_box_content`, `answer_dict`, `highlighted_answers`, `result`, and `title` in `haystack.components.websearch.serper_dev.SerperDevWebSearch.run`, defined in `haystack/components/websearch/serper_dev.py`.

A definition (“def”) is a binding of one of those names by an executed assignment target or parameter binding in the target function's own frame. Parameters count as definitions on the function's `def` line. A use is an executed read (a load of the name's current value) in that same frame. A pair `{“variable”: V, “def_line”: D, “use_line”: U}` is observed when the value most recently defined for V at D reaches a read at U before any intervening executed redefinition of V. Process reads on an ordinary assignment line before applying that line's assignment definitions. Augmented assignment such as `x += 1` first uses the old reaching definition of `x` and then creates a new definition of `x` on that same line, so it is both a use and a def. A `for x in ...` loop header creates a new definition of `x` on the header line for every successful iteration before the body executes. Executions in implicit comprehension frames and comprehension-local variables are excluded; a read evaluated in the target function's own frame is included.

An invocation means one `call` of the target function during this test, numbered 1-based in chronological order, although invocation numbers are not included in the answer. Include only definitions and reads that actually execute in the target's own frame; exclude callers, callees, and implicit comprehension frames. Aggregate pairs across every invocation, then remove exact duplicate triples. Multiple reads of the same variable on the same source line under the same reaching definition therefore produce one pair.

Line numbers are absolute, 1-based source line numbers in the named repository file. The def or use line is the source line on which that assignment target or variable-read expression begins. For a multi-line statement or expression, use the line where the relevant target or read expression begins; decorator and docstring lines do not count unless they themselves contain an executed tracked binding or read in the target frame.

Return a JSON object with exactly one key, `observed_def_use_pairs`, whose value is a JSON list of objects. Every object has exactly the keys `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string). Sort the list by `variable` lexicographically ascending, then `def_line` numerically ascending, then `use_line` numerically ascending. No values are serialized with `repr()` or `str()` because the answer contains only source variable names and integer line numbers."""


class _FunctionFacts(ast.NodeVisitor):
    def __init__(self, tracked):
        self.tracked = set(tracked)
        self.defs_by_line = {}
        self.uses_by_line = {}

    def visit_Name(self, node):
        if node.id in self.tracked:
            destination = self.uses_by_line if isinstance(node.ctx, ast.Load) else self.defs_by_line
            destination.setdefault(node.lineno, set()).add(node.id)

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
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


def source_facts(source_path):
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"cannot inspect target source {source_path}: {exc}") from exc

    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SerperDevWebSearch":
            target = next(
                (member for member in node.body if isinstance(member, ast.FunctionDef) and member.name == "run"),
                None,
            )
            break
    if target is None:
        raise RuntimeError("could not locate SerperDevWebSearch.run in target source")

    facts = _FunctionFacts(TRACKED)
    for statement in target.body:
        facts.visit(statement)

    parameter_defs = {}
    for argument in (*target.args.posonlyargs, *target.args.args, *target.args.kwonlyargs):
        if argument.arg in TRACKED:
            parameter_defs[argument.arg] = target.lineno
    if target.args.vararg and target.args.vararg.arg in TRACKED:
        parameter_defs[target.args.vararg.arg] = target.lineno
    if target.args.kwarg and target.args.kwarg.arg in TRACKED:
        parameter_defs[target.args.kwarg.arg] = target.lineno
    return facts.defs_by_line, facts.uses_by_line, parameter_defs


def observed_pairs(trace_path, defs_by_line, uses_by_line, parameter_defs):
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"(?P<path>\S*haystack/components/websearch/serper_dev\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    target_events = 0
    active_defs = None
    complete_invocations = 0
    pairs = set()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            if active_defs is not None:
                raise RuntimeError("overlapping target invocations found in trace")
            active_defs = dict(parameter_defs)
        elif event == "line":
            if active_defs is None:
                raise RuntimeError("target line event found outside an invocation")
            for variable in sorted(uses_by_line.get(line_number, ())):
                if variable not in active_defs:
                    raise RuntimeError(
                        f"executed use of {variable!r} at line {line_number} has no reaching definition"
                    )
                pairs.add((variable, active_defs[variable], line_number))
            for variable in sorted(defs_by_line.get(line_number, ())):
                active_defs[variable] = line_number
        elif event == "return":
            if active_defs is None:
                raise RuntimeError("target return event found without a matching call")
            active_defs = None
            complete_invocations += 1

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_defs is not None:
        raise RuntimeError("trace ended during an active target invocation")
    if complete_invocations == 0:
        raise RuntimeError(f"trace contains no complete invocations of {TARGET_FUNC}")
    if not pairs:
        raise RuntimeError("no observed def-use pairs were computed")

    return [
        {"variable": variable, "def_line": def_line, "use_line": use_line}
        for variable, def_line, use_line in sorted(pairs, key=lambda item: (item[0], item[1], item[2]))
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        defs_by_line, uses_by_line, parameter_defs = source_facts(TARGET_FILE)
        pairs = observed_pairs(args.trace_log, defs_by_line, uses_by_line, parameter_defs)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]
        },
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
