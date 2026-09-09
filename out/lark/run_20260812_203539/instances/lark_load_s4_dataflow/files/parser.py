from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/lark.py"
TARGET_FUNC = "lark.lark.Lark._load"
TRACKED = ("d", "data", "f", "kwargs", "memo", "memo_json", "options", "self")
PARAMETERS = ("self", "f", "kwargs")

QUESTION = """Run only the pytest test
`lark_qa/lark_load_s4_dataflow/files/testcase.py::TestProgrammaticSerializedLoads::test_mixed_direct_load_sources`.
For all invocations of `lark.lark.Lark._load` in `lark/lark.py` during that
test, report all unique observed dynamic def-use pairs for the local variables
`d`, `data`, `f`, `kwargs`, `memo`, `memo_json`, `options`, and `self`.

A definition is a binding of one of those local names by a parameter or an
assignment to that local name. Parameters count as definitions on the
function's `def` line. An attribute assignment such as `obj.value = item`
reads the local `obj` but does not redefine it. A use is a read of that local
name by the target function's own frame on an executed source line. A
definition reaches a use when it is the most recent definition of that name
earlier in the same invocation, with no intervening definition. Reads on a
line are evaluated against the reaching definition before definitions
performed by that same line. An augmented assignment such as `counter += 1`
therefore uses the old reaching definition and then creates a new definition
on that line. Each successful iteration of `for counter in values` creates a
new definition of `counter` on the loop-header line.

Comprehension iteration variables are local to the comprehension-generated
frame: exclude both their definitions and their reads, and do not let them
replace a same-named reaching definition in `_load`. Exclude every event and
read performed by such a nested comprehension frame. The evaluation of a
comprehension's outermost iterable occurs in `_load` itself, so reads made by
that outermost-iterable expression do count. Only reads performed by the
target function's own frame count. Treat each invocation independently,
where an invocation is one `call` of the target function, numbered 1-based in
chronological order, and then aggregate the pairs across every invocation in
the test.

Line numbers are absolute 1-based physical line numbers in the named
repository file as it exists for the test. For a multi-line statement or
expression, report the executed physical line on which the relevant read or
binding expression begins. The function `def` line can appear for tracked
parameter definitions; decorator and docstring lines do not count unless
they themselves read or define a tracked local. Remove duplicate
`(variable, def_line, use_line)` triples regardless of whether repetitions
occur within one invocation or across invocations. Return exactly
`{"observed_def_use_pairs": [...]}`, where each list element is exactly
`{"def_line": <JSON integer>, "use_line": <JSON integer>, "variable": <JSON string>}`.
Sort the list by `variable` in ascending Unicode code-point lexicographic
order, then by `def_line` and `use_line` numerically ascending; these fields
are the complete tie-break order."""


class LocalAccessVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.defs: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED:
            return
        destination = (
            self.defs
            if isinstance(node.ctx, (ast.Store, ast.Del))
            else self.uses
        )
        destination.setdefault(node.lineno, set()).add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def _visit_comprehension(self, node: ast.AST) -> None:
        generators = node.generators
        if generators:
            self.visit(generators[0].iter)

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension


def find_target(tree: ast.AST) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Lark":
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef) and statement.name == "_load":
                    return statement
    raise RuntimeError("could not find Lark._load in target source")


def source_accesses(
    source_path: Path,
) -> tuple[int, dict[int, set[str]], dict[int, set[str]]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = find_target(tree)
    visitor = LocalAccessVisitor()
    for statement in target.body:
        visitor.visit(statement)
    return target.lineno, visitor.defs, visitor.uses


TRACE_RE = re.compile(
    r" (?P<file>\S*lark/lark\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def trace_events(trace_path: Path) -> list[tuple[str, int]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int]] = []
    for raw_line in text.splitlines():
        match = TRACE_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((match.group("event"), int(match.group("line"))))
    if not events:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event == "line" for event, _ in events):
        raise RuntimeError(f"trace contains no line events for {TARGET_FUNC}")
    return events


def compute_pairs(
    events: list[tuple[str, int]],
    def_line: int,
    definitions: dict[int, set[str]],
    uses: dict[int, set[str]],
) -> list[dict[str, int | str]]:
    pairs: set[tuple[str, int, int]] = set()
    reaching: dict[str, int] | None = None
    invocation_count = 0

    for event, line in events:
        if event == "call":
            if reaching is not None:
                raise RuntimeError("overlapping target invocations are not supported")
            invocation_count += 1
            reaching = {parameter: def_line for parameter in PARAMETERS}
        elif event == "line":
            if reaching is None:
                raise RuntimeError("target line event occurred outside an invocation")
            for variable in sorted(uses.get(line, ())):
                if variable in reaching:
                    pairs.add((variable, reaching[variable], line))
            for variable in sorted(definitions.get(line, ())):
                reaching[variable] = line
        elif event == "return":
            if reaching is None:
                raise RuntimeError("target return event occurred outside an invocation")
            reaching = None
        elif event == "exception" and reaching is None:
            raise RuntimeError("target exception event occurred outside an invocation")

    if not invocation_count:
        raise RuntimeError("trace contains no target call events")
    if reaching is not None:
        raise RuntimeError("trace ended during a target invocation")
    if not pairs:
        raise RuntimeError("computed no observed def-use pairs")

    return [
        {"def_line": definition, "use_line": use, "variable": variable}
        for variable, definition, use in sorted(pairs)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source does not exist: {source_path}")

    def_line, definitions, uses = source_accesses(source_path)
    answer = {
        "observed_def_use_pairs": compute_pairs(
            trace_events(args.trace_log),
            def_line,
            definitions,
            uses,
        )
    }
    document = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(answer, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
