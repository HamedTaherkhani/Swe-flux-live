#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/utils/hf.py"
TARGET_FUNC = "haystack.utils.hf.convert_message_to_hf_format"
TRACKED_VARIABLES = {
    "content_parts",
    "hf_msg",
    "hf_tool_call",
    "hf_tool_calls",
    "image_url",
    "part",
    "tc",
    "tool_calls",
}

QUESTION = """Run the single pytest test
`haystack_qa/hf_convert_message_to_hf_format_s4_dataflow/files/testcase.py::TestHFMessageDataFlow::test_seeded_mixed_messages`
against this repository. Across all invocations made by that test, report the
unique observed dynamic def-use pairs in the exact function
`haystack.utils.hf.convert_message_to_hf_format` in
`haystack/utils/hf.py` for exactly these local variable names:
`content_parts`, `hf_msg`, `hf_tool_call`, `hf_tool_calls`, `image_url`,
`part`, `tc`, and `tool_calls`.

An invocation is one call entry into that exact function frame, numbered
1-based in chronological order, although invocation numbers are not emitted.
Analyze only reads and bindings performed by the target function's own frame;
do not include activity in callees. A definition ("def") is an assignment to
the named local or a parameter binding. Parameters count as defined on the
function's `def` line. A use is an actual evaluation-time read of that local's
current value on an executed source line. Attribute names and mapping keys are
not local-variable uses; reading a local in order to access its attribute,
subscript, or method is a use of that local. A pair
`{"def_line": D, "use_line": U, "variable": V}` is observed when the value
bound to V by the definition on D reaches a read on U before any later
definition of V in that invocation.

Process operations in Python evaluation order. For an ordinary assignment,
reads in its right-hand side use the prior reaching definition and the new
definition then takes effect. Augmented assignment such as `x += 1` both
reads and writes: its read uses the old reaching definition, and it creates a
new definition on that same line for subsequent reads. Each successful
`for x in iterable` iteration redefines `x` on the loop-header line; evaluating
the iterable is a use, while the final exhaustion check creates no definition.
Comprehension iteration variables are local to the comprehension's own
implicit frame and are excluded; reads performed in such a separate frame are
also excluded.

Line numbers are absolute, 1-based line numbers in
`haystack/utils/hf.py` as it exists in the repository. For a multi-line
statement or expression, use the line where the executed statement or
expression begins according to Python's source line table. The function
`def` line can appear only as a parameter-definition line; decorator and
docstring lines count only if they perform a tracked definition or read under
the rules above.

Aggregate pairs across every target invocation in the test and remove exact
duplicate triples, including duplicates caused by loop iterations or repeated
invocations. Return exactly one JSON object with the single key
`observed_def_use_pairs`. Its value is a JSON list of objects, each having
exactly `def_line` (JSON integer), `use_line` (JSON integer), and `variable`
(JSON string). Sort the list by `variable` ascending in Unicode code-point
order, then by `def_line` ascending, then by `use_line` ascending. These three
fields form a total key after exact duplicates are removed. No `repr()` or
`str()` formatting of runtime values is involved because the answer contains
only variable-name strings and integer source lines."""

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def target_syntax(source_path: Path):
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "convert_message_to_hf_format"
        ),
        None,
    )
    if function is None:
        fail(f"target function is missing from {source_path}")

    loads_by_line: dict[int, set[str]] = {}
    stores_by_line: dict[int, set[str]] = {}
    augmented_loads_by_line: dict[int, set[str]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id in TRACKED_VARIABLES:
            destination = loads_by_line if isinstance(node.ctx, ast.Load) else stores_by_line
            destination.setdefault(node.lineno, set()).add(node.id)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id in TRACKED_VARIABLES:
                augmented_loads_by_line.setdefault(node.lineno, set()).add(node.target.id)

    loop_body_start: dict[int, int] = {}
    loop_targets: dict[int, set[str]] = {}
    for node in ast.walk(function):
        if not isinstance(node, (ast.For, ast.AsyncFor)):
            continue
        names = {
            child.id
            for child in ast.walk(node.target)
            if isinstance(child, ast.Name) and child.id in TRACKED_VARIABLES
        }
        if names and node.body:
            loop_targets[node.lineno] = names
            loop_body_start[node.lineno] = node.body[0].lineno

    parameters = {
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
        if argument.arg in TRACKED_VARIABLES
    }
    if function.args.vararg and function.args.vararg.arg in TRACKED_VARIABLES:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg and function.args.kwarg.arg in TRACKED_VARIABLES:
        parameters.add(function.args.kwarg.arg)

    return (
        function.lineno,
        parameters,
        loads_by_line,
        stores_by_line,
        augmented_loads_by_line,
        loop_targets,
        loop_body_start,
    )


def read_invocations(trace_path: Path) -> list[list[int]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocations: list[list[int]] = []
    current: list[int] | None = None
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        path = match.group("path").replace("\\", "/")
        if not path.endswith(f"/{TARGET_FILE}") or match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if current is not None:
                fail("encountered nested or unterminated target invocation")
            current = []
        elif event == "line":
            if current is None:
                fail("target line event appeared outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            if current is None:
                fail("target return event appeared outside an invocation")
            invocations.append(current)
            current = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")
    if current is not None:
        fail("trace ended during a target invocation")
    if not invocations:
        fail(f"trace contains no completed invocations of {TARGET_FUNC}")
    return invocations


def compute_pairs(trace_path: Path, source_path: Path) -> dict[str, list[dict[str, object]]]:
    (
        def_line,
        parameters,
        loads_by_line,
        stores_by_line,
        augmented_loads_by_line,
        loop_targets,
        loop_body_start,
    ) = target_syntax(source_path)
    invocations = read_invocations(trace_path)

    pairs: set[tuple[str, int, int]] = set()
    for executed_lines in invocations:
        reaching = {name: def_line for name in parameters}
        for index, line in enumerate(executed_lines):
            uses = loads_by_line.get(line, set()) | augmented_loads_by_line.get(line, set())
            for variable in uses:
                if variable not in reaching:
                    fail(f"use of tracked variable {variable!r} on line {line} has no reaching definition")
                pairs.add((variable, reaching[variable], line))

            definitions = set(stores_by_line.get(line, set()))
            if line in loop_targets:
                next_line = executed_lines[index + 1] if index + 1 < len(executed_lines) else None
                if next_line != loop_body_start[line]:
                    definitions -= loop_targets[line]
            for variable in definitions:
                reaching[variable] = line

    if not pairs:
        fail("computed no observed def-use pairs")
    rows = [
        {"def_line": definition, "use_line": use, "variable": variable}
        for variable, definition, use in sorted(pairs)
    ]
    return {"observed_def_use_pairs": rows}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": compute_pairs(args.trace_log, source_path),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(oracle, indent=2, sort_keys=True) + "\n"
    args.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    try:
        main()
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
