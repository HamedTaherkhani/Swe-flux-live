#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/sansio/blueprints.py"
TARGET_FUNC = "flask.sansio.blueprints.BlueprintSetupState.add_url_rule"
TARGET_CLASS = "BlueprintSetupState"
TARGET_METHOD = "add_url_rule"
TRACKED_VARIABLES = ("defaults", "endpoint", "rule")

QUESTION = """Run the pytest test `flask_qa/blueprints_add_url_rule_m4_dataflow/files/testcase.py::TestGeneratedBlueprintRegistration::test_registers_generated_rule_matrix`. During that complete test run, consider only invocations of `flask.sansio.blueprints.BlueprintSetupState.add_url_rule` in `src/flask/sansio/blueprints.py`. Across all of those invocations, what unique observed reaching-definition/use pairs occur for exactly the local variables `defaults`, `endpoint`, and `rule`?

An invocation is one call of this exact function, numbered from 1 in chronological order across the test run. Analyze only the target function's own frame: do not include callers, callees, nested function or lambda frames, or comprehension frames. A definition is the successful binding of one of the three tracked local names. Treat a parameter as defined at the function's `def` line on every invocation. A plain assignment defines its target only after its right-hand side completes successfully. In a chained or destructuring assignment, every tracked target successfully bound by that statement is defined at the line where the assignment statement begins. A `for` header defines a tracked target on each successful iteration binding, at the line where that header begins; reads used to produce the next iterable item occur before that iteration's binding. An augmented assignment such as the unrelated `total += step` first uses the reaching definition of `total` and then, after the operation succeeds, defines `total` again on that augmented-assignment line. A walrus assignment evaluates its right-hand side reads before its successful definition. Comprehension induction variables are comprehension-local and are excluded, and loads performed in comprehension frames are excluded.

A use is an actually executed read represented by an AST `Name` node with `Load` context for one of the tracked names in the target frame; truth tests, call arguments, and right-hand sides count. Attribute names and dictionary keys do not count as local-name uses. A pair is observed when a use executes and the most recent successful definition of the same variable in that invocation reaches it without another definition intervening. Definitions never reach across invocations. If the same variable is read more than once on one source line from the same reaching definition, that still yields one pair after deduplication.

Line numbers are absolute, 1-based line numbers in `src/flask/sansio/blueprints.py` as it exists in the repository. A parameter definition is attributed to the line where the function's `def` statement begins. For a multi-line assignment or loop header, a definition is attributed to the line where that statement begins; a use is attributed to the line where its AST `Name` expression begins. Decorator and docstring lines produce no pair unless they contain an actually executed tracked-name use in the target frame.

Return exactly one JSON object with the shape `{"observed_def_use_pairs": [{"def_line": 1, "use_line": 2, "variable": "name"}]}`. `observed_def_use_pairs` is a JSON array. Each entry has exactly the keys `def_line`, `use_line`, and `variable`; both line fields are JSON integers and `variable` is the bare local-name JSON string. Take the union across all invocations, remove duplicate triples, then sort in ascending order by `variable` using Unicode code-point order, then by numeric `def_line`, then by numeric `use_line`. Do not emit invocation numbers, values, unobserved static possibilities, JSON nulls, or any other keys."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_event(raw_line: str) -> dict[str, object] | None:
    match = re.match(
        r"^(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} )?"
        r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
        r"event=(?P<event>\w+)\b",
        raw_line,
    )
    if match is None:
        return None
    return {
        "file": match.group("file").replace("\\", "/"),
        "line": int(match.group("line")),
        "func": match.group("func"),
        "event": match.group("event"),
    }


class FunctionBindings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.definitions: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}

    def add_definition(self, name: str, line: int) -> None:
        if name in TRACKED_VARIABLES:
            self.definitions.setdefault(line, set()).add(name)

    def add_use(self, name: str, line: int) -> None:
        if name in TRACKED_VARIABLES:
            self.uses.setdefault(line, set()).add(name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.add_use(node.id, node.lineno)
        elif isinstance(node.ctx, ast.Store):
            self.add_definition(node.id, node.lineno)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.add_use(node.target.id, node.lineno)
            self.add_definition(node.target.id, node.lineno)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return


def source_flow(source_path: Path) -> tuple[int, set[str], dict[int, set[str]], dict[int, set[str]]]:
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target: ast.FunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == TARGET_METHOD:
                    target = child
                    break
    if target is None:
        fail(f"could not find {TARGET_CLASS}.{TARGET_METHOD} in {source_path}")

    parameter_names = {
        arg.arg
        for arg in (
            list(target.args.posonlyargs)
            + list(target.args.args)
            + list(target.args.kwonlyargs)
        )
        if arg.arg in TRACKED_VARIABLES
    }
    if target.args.vararg and target.args.vararg.arg in TRACKED_VARIABLES:
        parameter_names.add(target.args.vararg.arg)
    if target.args.kwarg and target.args.kwarg.arg in TRACKED_VARIABLES:
        parameter_names.add(target.args.kwarg.arg)

    bindings = FunctionBindings()
    for statement in target.body:
        bindings.visit(statement)
    return target.lineno, parameter_names, bindings.definitions, bindings.uses


def harvest(trace_path: Path, source_path: Path) -> dict[str, list[dict[str, object]]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in raw.splitlines():
        event = parse_event(raw_line)
        if (
            event is not None
            and str(event["file"]).endswith(TARGET_FILE)
            and event["func"] == TARGET_FUNC
        ):
            events.append(event)
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    def_line, parameters, definitions, uses = source_flow(source_path)
    pairs: set[tuple[str, int, int]] = set()
    active = False
    current_definition: dict[str, int] = {}
    pending_definitions: dict[str, int] = {}
    invocation_count = 0

    for event in events:
        event_kind = str(event["event"])
        event_line = int(event["line"])

        if event_kind == "call":
            if active:
                fail("encountered a nested target invocation in one trace stream")
            if event_line != def_line:
                fail(
                    f"target call event was at line {event_line}, expected {def_line}"
                )
            active = True
            invocation_count += 1
            current_definition = {name: def_line for name in parameters}
            pending_definitions = {}
            continue

        if not active:
            fail(f"encountered target {event_kind} event outside an invocation")

        if event_kind == "line":
            current_definition.update(pending_definitions)
            pending_definitions = {}

            for name in uses.get(event_line, set()):
                if name not in current_definition:
                    fail(
                        f"use of {name!r} at line {event_line} has no reaching definition"
                    )
                pairs.add((name, current_definition[name], event_line))

            pending_definitions = {
                name: event_line for name in definitions.get(event_line, set())
            }
        elif event_kind == "exception":
            pending_definitions = {}
        elif event_kind == "return":
            active = False
            current_definition = {}
            pending_definitions = {}

    if active:
        fail("trace ended during a target invocation")
    if invocation_count == 0:
        fail(f"trace contains no calls of {TARGET_FUNC}")
    if not pairs:
        fail("target events produced zero observed def-use pairs")

    return {
        "observed_def_use_pairs": [
            {"def_line": def_site, "use_line": use_site, "variable": variable}
            for variable, def_site, use_site in sorted(pairs)
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": harvest(args.trace_log, Path(TARGET_FILE)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, SyntaxError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
