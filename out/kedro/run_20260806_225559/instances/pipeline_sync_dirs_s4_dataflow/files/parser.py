from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/cli/pipeline.py"
TARGET_FUNC = "kedro.framework.cli.pipeline._sync_dirs"
TARGET_NAME = "_sync_dirs"
VARIABLES = (
    "content",
    "existing",
    "existing_files",
    "existing_folders",
    "new_prefix",
    "overwrite",
    "prefix",
    "source",
    "source_name",
    "source_path",
    "target",
    "target_path",
)
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/pipeline_sync_dirs_s4_dataflow/files/testcase.py::TestPipelineSyncDataFlow::test_generated_create_tree`
against this repository. Across all invocations during that test, what unique
runtime def-use pairs are observed in the exact function frame
`kedro.framework.cli.pipeline._sync_dirs` from
`kedro/framework/cli/pipeline.py` for the local variables `content`, `existing`,
`existing_files`, `existing_folders`, `new_prefix`, `overwrite`, `prefix`,
`source`, `source_name`, `source_path`, `target`, and `target_path`?

A def-use pair is an object recording that a value defined for one named local
at `def_line` is subsequently read at `use_line` in the same invocation before
that local is redefined. A definition is an executed assignment to that local
or its parameter binding. Parameters count as defined on the first physical
line of the function's `def` statement, even when the signature spans several
lines. An ordinary assignment's definition is on the physical line containing
its target name. A use is an actual runtime read of the local, not merely a
name present on a path that was skipped by branching or Boolean
short-circuiting. Assignment targets are not reads.

Treat augmented assignment as reading and then writing: for example,
`count += step` first creates a use of `count`'s old reaching definition on
that line and then a new definition of `count` on the same line. A loop header
such as `for item in items` reads `items` and redefines `item` on every
executed iteration, before the body for that iteration. Comprehension-local
variables, including a comprehension's iteration variable, belong to the
comprehension frame and are excluded; a read performed by the exact target
frame to supply a comprehension's outermost iterable still counts. For
example, in `sum(v for v in items)`, `v` is comprehension-local while the
outer-frame read of `items` counts if `items` is tracked.

Only reads and definitions executed by an exact `_sync_dirs` frame count.
Do not include activity in callees or comprehension frames. Each function
invocation starts fresh: a definition in one invocation cannot reach a use in
another, including between a recursive caller and callee. An invocation means
one call of the exact function during the test, numbered 1-based in
chronological call order, although invocation numbers are not reported.
Combine the pairs from all invocations, remove duplicate objects having the
same variable, definition line, and use line, and retain pairs observed at
least once.

`def_line` and `use_line` are JSON integers containing absolute, 1-based
physical source line numbers in the named file as it exists in this
repository. For a multi-line statement or expression, attribute an operation
to the physical line where that particular assignment target or read
expression begins. The function's first `def` line can therefore appear only
as the parameter-definition line; decorator and docstring lines are not
definitions or uses unless they themselves contain an executed operation
covered by the rules above.

The complete answer must have exactly the JSON shape
`{"observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]}`.
`observed_def_use_pairs` is a JSON array. Every element has exactly those three
keys: `variable` is the local's exact source spelling as a JSON string, while
`def_line` and `use_line` are JSON integers (not quoted strings). Sort the
array by `variable` in ascending Unicode code-point order, then by `def_line`
ascending, then by `use_line` ascending. Apart from removing exact duplicate
triples as specified above, do not merge or omit entries. The `"str"` and
`"int"` values in the shape are type placeholders, not answer values."""


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
        destination = uses if isinstance(node.ctx, ast.Load) else definitions
        if isinstance(node.ctx, (ast.Load, ast.Store)):
            destination.setdefault(node.lineno, set()).add(node.id)

    for node in ast.walk(target):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id in tracked:
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
            stack.append({})
            frame_definitions = stack[-1]
            for parameter in parameters:
                if parameter in VARIABLES:
                    frame_definitions[parameter] = parameter_line
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
        "question_kind": "S4_DataFlow",
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
