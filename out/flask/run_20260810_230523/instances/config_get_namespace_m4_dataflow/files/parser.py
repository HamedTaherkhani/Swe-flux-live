import argparse
import ast
import json
from pathlib import Path
import re
import sys


INSTANCE_TEST = (
    "flask_qa/config_get_namespace_m4_dataflow/files/testcase.py::"
    "TestConfigNamespaceDataFlow::test_seeded_namespace_matrix"
)
TARGET_FILE = "src/flask/config.py"
TARGET_FUNC = "flask.config.Config.get_namespace"
TRACKED = {
    "self",
    "namespace",
    "lowercase",
    "trim_namespace",
    "rv",
    "k",
    "v",
    "key",
}

QUESTION = f"""Run the pytest test `{INSTANCE_TEST}` against this repository. Across
all invocations of `{TARGET_FUNC}` in `{TARGET_FILE}` during that test, what
are all unique observed reaching-definition/use pairs for exactly these local
variables: `self`, `namespace`, `lowercase`, `trim_namespace`, `rv`, `k`, `v`,
and `key`?

An invocation is one entry into exactly `{TARGET_FUNC}`, counted 1-based in
chronological order over the entire test run. Analyze every invocation, but a
definition can reach uses only within its own invocation; then take the union
of the resulting pairs. Ignore nested callees and all other frames.

A definition is a runtime execution that binds a tracked simple local name.
The four parameters `self`, `namespace`, `lowercase`, and `trim_namespace`
are defined at the function's `def` line when each invocation starts.
Execution of a plain assignment defines each tracked `Name` target after its
right-hand side has been evaluated. Assignment through an attribute or
subscript is not a definition of the base name (for example, `box[i] = x`
uses `box` and `i` but does not define `box`). A successful `for` iterator
step defines each simple name in its loop target at the loop-header line
before the body executes; the final iterator check that exits the loop does
not define the target. An augmented assignment such as `x += y` first uses
the prior `x` and then defines `x`, both at that statement's starting line.

A use is runtime evaluation of a tracked `Name` in load context in the
target frame, including names used in conditions, call arguments, return
expressions, right-hand sides, and the base or index of a subscript target.
Store-only name occurrences are not uses. For a statement that both uses and
defines the same name, pair its use with the definition that reached the
start of the statement, then install the new definition. A use is paired
with the most recent definition of that variable earlier in the same
invocation. Include a pair only when both that dynamic definition and use
actually occur on the executed path. Comprehension iteration variables would
belong to the comprehension's implicit nested scope and are excluded; there
are no comprehension-local variables in the tracked list.

`def_line` and `use_line` are absolute 1-based physical line numbers in
`{TARGET_FILE}` as it exists in the repository. For a multi-line statement or
expression, attribute definitions and uses to the physical line where the
smallest enclosing AST statement begins. Parameter definitions are attributed
to the function's `def` line, not continuation lines. Decorator and docstring
lines do not count as uses or definitions unless they are executable
statements in the target frame.

Deduplicate pairs by the complete triple `(variable, def_line, use_line)`
after unioning all invocations. Sort the final list by `variable`
lexicographically ascending by Python string ordering, then by `def_line`
numerically ascending, then by `use_line` numerically ascending. Return
exactly one JSON object with the shape
`{{"observed_def_use_pairs": [{{"def_line": "int", "use_line": "int", "variable": "str"}}]}}`
and no other keys. `variable` is the exact source identifier as a JSON string;
line values are JSON integers (not strings), and no value may be `null` or
omitted."""


def find_target(source_path: Path) -> ast.FunctionDef:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot read target source {source_path}: {exc}") from exc
    tree = ast.parse(source, filename=str(source_path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "get_namespace":
                    return child
    raise RuntimeError("target function Config.get_namespace was not found")


def loaded_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
        and child.id in TRACKED
    }


def defined_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Store)
        and child.id in TRACKED
    }


def statement_actions(target: ast.FunctionDef) -> dict[int, tuple[set[str], set[str], bool]]:
    actions = {}
    for statement in ast.walk(target):
        if not isinstance(statement, ast.stmt) or statement is target:
            continue

        uses: set[str]
        definitions: set[str]
        loop_header = False
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            value = statement.value
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            uses = loaded_names(value)
            definitions = set().union(*(defined_names(item) for item in targets))
            for item in targets:
                uses.update(loaded_names(item))
        elif isinstance(statement, ast.AugAssign):
            uses = loaded_names(statement.target) | loaded_names(statement.value)
            definitions = defined_names(statement.target)
            if isinstance(statement.target, ast.Name) and statement.target.id in TRACKED:
                uses.add(statement.target.id)
                definitions.add(statement.target.id)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            uses = loaded_names(statement.iter)
            definitions = defined_names(statement.target)
            loop_header = True
        elif isinstance(statement, (ast.If, ast.While)):
            uses = loaded_names(statement.test)
            definitions = set()
        elif isinstance(statement, ast.Return):
            uses = loaded_names(statement.value)
            definitions = set()
        elif isinstance(statement, ast.Expr):
            uses = loaded_names(statement.value)
            definitions = set()
        else:
            uses = set()
            definitions = set()

        actions[statement.lineno] = (uses, definitions, loop_header)
    return actions


def parse_trace(trace_path: Path, source_path: Path) -> dict:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"(?P<file>\S*src/flask/config\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    invocations: list[list[int]] = []
    current: list[int] | None = None
    target_events = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        if event == "call":
            if current is not None:
                raise RuntimeError("overlapping target invocations in trace")
            current = []
            invocations.append(current)
        elif current is None:
            raise RuntimeError(f"target {event} event occurred outside an invocation")
        elif event == "line":
            current.append(int(match.group("line")))
        elif event == "exception":
            raise RuntimeError("unexpected exception event in target invocation")
        elif event == "return":
            current = None

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET_FUNC}"
        )
    if current is not None:
        raise RuntimeError("trace ended during a target invocation")
    if not invocations or any(not invocation for invocation in invocations):
        raise RuntimeError("trace contains no complete non-empty target invocation")

    target = find_target(source_path)
    actions = statement_actions(target)
    parameters = {
        argument.arg
        for argument in (
            target.args.posonlyargs + target.args.args + target.args.kwonlyargs
        )
        if argument.arg in TRACKED
    }
    pairs: set[tuple[str, int, int]] = set()

    for lines in invocations:
        reaching = {name: target.lineno for name in parameters}
        for index, line in enumerate(lines):
            if line not in actions:
                raise RuntimeError(f"executed line {line} has no statement action")
            uses, definitions, loop_header = actions[line]
            for variable in uses:
                if variable not in reaching:
                    raise RuntimeError(
                        f"use of {variable!r} at line {line} has no reaching definition"
                    )
                pairs.add((variable, reaching[variable], line))

            if loop_header:
                next_line = lines[index + 1] if index + 1 < len(lines) else None
                loop_node = next(
                    item
                    for item in ast.walk(target)
                    if isinstance(item, (ast.For, ast.AsyncFor))
                    and item.lineno == line
                )
                body_first_line = loop_node.body[0].lineno
                if next_line == body_first_line:
                    for variable in definitions:
                        reaching[variable] = line
            else:
                for variable in definitions:
                    reaching[variable] = line

    if not pairs:
        raise RuntimeError("no observed def-use pairs were computed")
    return {
        "observed_def_use_pairs": [
            {"def_line": def_line, "use_line": use_line, "variable": variable}
            for variable, def_line, use_line in sorted(pairs)
        ]
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    answer = parse_trace(args.trace_log, root / TARGET_FILE)
    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote oracle to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
