from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/ipython/__init__.py"
TARGET_FUNC = "kedro.ipython._prepare_imports"
TARGET_NAME = "_prepare_imports"
VARIABLES = (
    "_",
    "clean_imports",
    "file",
    "import_statement",
    "inside_bracket",
    "line",
    "node_func",
    "python_file",
)
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/ipython_prepare_imports_m4_dataflow/files/testcase.py::TestIPythonPrepareImportsDataFlow::test_generated_magic_sources`
against this repository. Across all invocations during that test, what unique
runtime def-use pairs are observed in the exact function frame
`kedro.ipython._prepare_imports` from `kedro/ipython/__init__.py` for exactly
the local variables `_`, `clean_imports`, `file`, `import_statement`,
`inside_bracket`, `line`, `node_func`, and `python_file`?

A def-use pair records that a value defined for one tracked local at
`def_line` is subsequently read at `use_line` in the same invocation before
that local is redefined. A definition is an executed assignment to the local,
an executed `with ... as name` binding, an executed loop-target binding, or a
parameter binding. Parameters count as defined on the first physical line of
the function's `def` statement, even when a signature spans lines. An
ordinary assignment's definition is on the physical line containing its
target name; reads in its right-hand side occur before that definition. A
`with` alias is defined on the physical line containing that alias after the
context manager is entered. Assignment targets are not reads.

A use is an actual runtime read by the exact target frame. A name in a branch
that is not taken, or in an operand skipped by Boolean short-circuiting, is
not a use. Multiple reads producing the same variable/definition/use-line
triple still contribute only one pair. Treat augmented assignment as reading
and then writing: for example, `count += step` uses the old reaching
definition of `count` on that line and then defines `count` on that same
line. A loop header such as `for item in items` reads `items` when its
iterable expression is evaluated and defines `item` on that header's physical
line once for each successful iteration, before executing that iteration's
body; exhaustion does not define `item`.

Comprehension-local variables, including a comprehension's iteration
variable, belong to the comprehension frame and are excluded. A read
performed by the exact target frame to supply a comprehension's outermost
iterable still counts. For example, in `sum(v for v in values)`, `v` is
comprehension-local, while the target-frame read of `values` counts if it is
one of the explicitly tracked variables.

Only operations executed by an exact `kedro.ipython._prepare_imports` frame
count; exclude callees, caller frames, and comprehension or generator frames.
An invocation means one `call` of that exact function during the named test,
numbered 1-based in chronological call order, although invocation numbers are
not included in the answer. Each invocation starts with fresh reaching
definitions: no definition can reach from one invocation into another.
Union the pairs observed across all invocations, retain a triple observed at
least once, and remove exact duplicates by all three fields.

`def_line` and `use_line` are JSON integers containing absolute, 1-based
physical source line numbers in the named repository file as it exists for
this run. For a multi-line statement or expression, attribute each assignment
or read to the physical line where that particular target or name expression
begins. The first `def` line can appear only for parameter definitions.
Decorator and docstring lines do not count unless they themselves execute an
operation covered by the rules above.

The complete answer must have exactly the JSON shape
`{"observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]}`.
`observed_def_use_pairs` is a JSON array, and each element has exactly those
three keys. `variable` is the local's exact source spelling encoded as a JSON
string; `def_line` and `use_line` are JSON numbers encoded as unquoted
integers. No field is omitted or represented by JSON `null`. Sort the array
first by `variable` in ascending Unicode code-point order, then by `def_line`
ascending, then by `use_line` ascending. Apart from exact-triple
deduplication, do not merge or omit entries. The `"str"` and `"int"` values
shown in the shape are type placeholders, not answer values."""


def _target_node(source_path: Path) -> ast.FunctionDef:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_NAME
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one top-level {TARGET_NAME} in {source_path}"
        )
    return matches[0]


def _operations_by_line(
    target: ast.FunctionDef,
) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    tracked = set(VARIABLES)
    uses: dict[int, set[str]] = {}
    definitions: dict[int, set[str]] = {}

    for node in ast.walk(target):
        if not isinstance(node, ast.Name) or node.id not in tracked:
            continue
        if isinstance(node.ctx, ast.Load):
            uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, ast.Store):
            definitions.setdefault(node.lineno, set()).add(node.id)

    for node in ast.walk(target):
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in tracked
        ):
            uses.setdefault(node.target.lineno, set()).add(node.target.id)

    return uses, definitions


def _read_pairs(
    trace_path: Path,
    uses: dict[int, set[str]],
    definitions: dict[int, set[str]],
    parameter_line: int,
    parameters: tuple[str, ...],
) -> list[dict[str, int | str]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    stack: list[dict[str, int]] = []
    pairs: set[tuple[str, int, int]] = set()

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file").replace("\\", "/").endswith(
                f"/{TARGET_FILE}"
            )
        ):
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            stack.append(
                {
                    parameter: parameter_line
                    for parameter in parameters
                    if parameter in VARIABLES
                }
            )
            continue

        if not stack:
            raise RuntimeError(f"target {event} event appeared outside a call")

        if event == "line":
            reaching_definitions = stack[-1]
            for variable in uses.get(line, ()):
                if variable not in reaching_definitions:
                    raise RuntimeError(
                        f"use of {variable} on line {line} has no reaching definition"
                    )
                pairs.add((variable, reaching_definitions[variable], line))
            for variable in definitions.get(line, ()):
                reaching_definitions[variable] = line
        elif event == "return":
            stack.pop()

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if stack:
        raise RuntimeError(f"trace ended with {len(stack)} unfinished target call(s)")
    if not pairs:
        raise RuntimeError("trace produced no observed def-use pairs")

    return [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    target = _target_node(Path.cwd() / TARGET_FILE)
    uses, definitions = _operations_by_line(target)
    observed_pairs = _read_pairs(
        args.trace_log,
        uses,
        definitions,
        parameter_line=target.lineno,
        parameters=tuple(argument.arg for argument in target.args.args),
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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
