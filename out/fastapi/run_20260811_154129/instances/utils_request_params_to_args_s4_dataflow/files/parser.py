#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path
from typing import NoReturn


TARGET_FUNC = "fastapi.dependencies.utils.request_params_to_args"
TARGET_NAME = "request_params_to_args"
TRACKED_VARIABLES = (
    "alias",
    "errors_",
    "field_info",
    "loc",
    "params_to_process",
    "v_",
    "value",
    "values",
)

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<path>.+/fastapi/dependencies/utils\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


class ImmediateNameAccesses(ast.NodeVisitor):
    """Collect accesses in one statement, without entering child statements/scopes."""

    def __init__(self) -> None:
        self.loads: set[str] = set()
        self.stores: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loads.add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.stores.add(node.id)

    def visit_stmt(self, node: ast.stmt) -> None:
        return

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return


def statement_accesses(
    target: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[dict[int, set[str]], dict[int, set[str]], int, set[str]]:
    uses_by_line: dict[int, set[str]] = {}
    defs_by_line: dict[int, set[str]] = {}

    def analyze_statement(statement: ast.stmt) -> None:
        collector = ImmediateNameAccesses()
        for _field_name, value in ast.iter_fields(statement):
            if isinstance(value, ast.stmt):
                continue
            if isinstance(value, list):
                for item in value:
                    if not isinstance(item, ast.stmt):
                        collector.visit(item)
            elif isinstance(value, ast.AST):
                collector.visit(value)

        # Python's AST marks an augmented-assignment target as Store even
        # though its old value is read before the replacement value is stored.
        if isinstance(statement, ast.AugAssign) and isinstance(
            statement.target, ast.Name
        ):
            collector.loads.add(statement.target.id)

        if collector.loads:
            uses_by_line.setdefault(statement.lineno, set()).update(collector.loads)
        if collector.stores:
            defs_by_line.setdefault(statement.lineno, set()).update(collector.stores)

        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.stmt):
                analyze_statement(child)

    for item in target.body:
        analyze_statement(item)

    parameters = {
        argument.arg
        for argument in (
            list(target.args.posonlyargs)
            + list(target.args.args)
            + list(target.args.kwonlyargs)
        )
    }
    if target.args.vararg is not None:
        parameters.add(target.args.vararg.arg)
    if target.args.kwarg is not None:
        parameters.add(target.args.kwarg.arg)
    return uses_by_line, defs_by_line, target.lineno, parameters


def load_target(
    source_path: Path,
) -> tuple[
    dict[int, set[str]],
    dict[int, set[str]],
    int,
    set[str],
]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == TARGET_NAME
    ]
    if len(matches) != 1:
        fail(f"expected one top-level {TARGET_NAME}, found {len(matches)}")
    return statement_accesses(matches[0])


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[Path, int, str]] = []
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                (
                    Path(match.group("path")),
                    int(match.group("line")),
                    match.group("event"),
                )
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    source_paths = {path for path, _line, _event in events}
    if len(source_paths) != 1:
        fail(f"expected one target source path, found {len(source_paths)}")
    uses_by_line, defs_by_line, def_line, parameters = load_target(
        next(iter(source_paths))
    )

    observed_pairs: set[tuple[str, int, int]] = set()
    current_defs: dict[str, int] = {}
    active = False
    calls = 0
    returns = 0
    line_events = 0
    executed_lines: set[int] = set()

    for _path, line_number, event in events:
        if event == "call":
            if active:
                fail("unexpected recursive or overlapping target invocation")
            active = True
            calls += 1
            current_defs = {
                variable: def_line
                for variable in TRACKED_VARIABLES
                if variable in parameters
            }
            continue
        if not active:
            fail(f"target {event} event occurred outside an invocation")
        if event == "line":
            line_events += 1
            executed_lines.add(line_number)
            for variable in sorted(uses_by_line.get(line_number, set())):
                if variable in TRACKED_VARIABLES and variable in current_defs:
                    observed_pairs.add(
                        (variable, current_defs[variable], line_number)
                    )
            for variable in sorted(defs_by_line.get(line_number, set())):
                if variable in TRACKED_VARIABLES:
                    current_defs[variable] = line_number
        elif event == "return":
            active = False
            returns += 1

    if active:
        fail("trace ended during a target invocation")
    if calls == 0 or returns != calls:
        fail(f"incomplete target calls: calls={calls}, returns={returns}")
    if line_events < 40 or len(executed_lines) < 8:
        fail(
            "trace is not rich enough: "
            f"line_events={line_events}, distinct_lines={len(executed_lines)}"
        )
    if len(observed_pairs) < 8:
        fail(f"def-use answer is not rich enough: pairs={len(observed_pairs)}")

    answer = {
        "observed_def_use_pairs": [
            {
                "def_line": definition_line,
                "use_line": use_line,
                "variable": variable,
            }
            for variable, definition_line, use_line in sorted(observed_pairs)
        ]
    }
    question = (
        "Run only the pytest test "
        "`fastapi_qa/utils_request_params_to_args_s4_dataflow/files/"
        "testcase.py::TestRequestParameterDataFlow::"
        "test_generated_query_header_and_dependency_inputs`. Across every "
        "invocation during that test of "
        "`fastapi.dependencies.utils.request_params_to_args` in "
        "`fastapi/dependencies/utils.py`, report all unique observed dynamic "
        "def-use pairs for exactly these local variables: `alias`, `errors_`, "
        "`field_info`, `loc`, `params_to_process`, `v_`, `value`, and `values`. "
        "An invocation is one runtime call of exactly that dotted function, "
        "numbered 1-based in chronological call-entry order; aggregate over "
        "all invocations, and reset reaching definitions at each call. A def "
        "is a completed assignment to the local name or a parameter binding; "
        "a parameter binding is defined on the function's `def` line. A use "
        "is a runtime read of that local name by code executing in the target "
        "function's own frame. Exclude reads and writes in callees, nested "
        "function frames, and comprehension or generator-expression frames; "
        "comprehension-local iteration variables therefore never count. For "
        "an ordinary assignment, evaluate and count all right-hand-side uses "
        "before its target becomes the new reaching def. Treat augmented "
        "assignment such as `counter += step` as both a use of `counter`'s "
        "old reaching def and a new def of `counter` on that same line. A "
        "`for item in iterable` header reads `iterable` whenever the header "
        "is evaluated and redefines `item` once for each successful "
        "iteration before the body executes; the final exhaustion check does "
        "not define `item`. A pair is observed when an executed use reads the "
        "value from the most recent def of the same variable in that "
        "invocation, with no intervening completed def. Source line numbers "
        "are absolute, 1-based lines in the named repository file. For a "
        "multi-line statement or expression, attribute all of its defs and "
        "uses to the line where that statement or expression begins; the "
        "function `def` line counts only for parameter bindings, not as an "
        "ordinary executed body line. Remove duplicate "
        "`(variable, def_line, use_line)` triples across repeated iterations "
        "and invocations. Return exactly one JSON object with key "
        "`observed_def_use_pairs`, whose value is a JSON list of objects with "
        "exactly the keys `def_line` (integer), `use_line` (integer), and "
        "`variable` (string). Sort the list by `variable` using ordinary "
        "case-sensitive string order, then by `def_line`, then by `use_line`, "
        "both numerically ascending. The integers are emitted as JSON "
        "numbers and variable names as JSON strings; no `repr()`/`str()` "
        "conversion, null, omitted-field, or exception/function-name "
        "formatting convention applies to these fields."
    )
    result = {
        "question_kind": "S4_DataFlow",
        "question": question,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
