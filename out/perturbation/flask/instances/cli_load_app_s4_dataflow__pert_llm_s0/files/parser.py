#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "src/flask/cli.py"
TARGET_FUNC = "flask.cli.ScriptInfo.load_app"
TRACKED_VARIABLES = ("app", "import_name", "name", "path", "self")

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/cli_load_app_s4_dataflow/files/testcase.py::"
    "LoadAppDataFlowTest::test_generated_cli_sessions`. Across all invocations "
    "of exactly `flask.cli.ScriptInfo.load_app` in the repo-relative file "
    "`src/flask/cli.py` during that test run, report all unique observed "
    "dynamic def-use pairs for the local variables `app`, `import_name`, "
    "`name`, `path`, and `self`. A def is an executed binding of one of those "
    "names by assignment or loop-target binding; each function parameter is "
    "defined when its invocation begins, at the function's `def` line. A use "
    "is an executed read of that local name, including a read as the base of "
    "an attribute access, in a condition, call, return expression, or "
    "assignment right-hand side. A pair is `{variable, def_line, use_line}` "
    "when the value produced by the most recent def of `variable` in the same "
    "function invocation is read at `use_line` before another def of that "
    "variable executes. Assignment targets are not uses. An augmented "
    "assignment such as `total += item` first uses the old reaching def of "
    "`total` and then creates a new def of `total` on that same line. A loop "
    "header such as `for item in values` uses `values` and creates a new def "
    "of `item` on the header line on every iteration. Comprehension-local "
    "variables are scoped to their comprehension frame and are excluded, as "
    "are all events and reads in callees or other nested frames. Count only "
    "reads and bindings executed in the exact target function frame. An "
    "invocation means one call of exactly that function, counted 1-based in "
    "chronological order, although invocation numbers are not included in the "
    "answer. Line numbers are absolute 1-based source line numbers in the "
    "named file as it exists in the repository. For a multi-line statement or "
    "expression, a def or use is attributed to the physical source line where "
    "that variable binding or read begins. The parameter def may therefore "
    "use the function's `def` line; decorator and docstring lines do not count "
    "unless they execute a qualifying binding or read in the target frame. "
    "Remove duplicate triples observed across iterations or invocations, then "
    "sort the remaining objects by `variable` ascending, then `def_line` "
    "ascending, then `use_line` ascending. Return exactly one JSON object with "
    "the key `observed_def_use_pairs`, whose value is a JSON array of objects; "
    "each object has exactly the keys `def_line` (JSON integer), `use_line` "
    "(JSON integer), and `variable` (JSON string containing the exact local "
    "name). No Python `repr` or `str` conversion is applied to these names or "
    "line numbers."
)

EVENT_RE = re.compile(
    r"(?P<file>\S*src/flask/cli\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def target_function(source_path: Path) -> ast.FunctionDef:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ScriptInfo":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "load_app":
                    return child

    fail(f"cannot find ScriptInfo.load_app in {source_path}")


class DefUseVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.defs: dict[int, set[str]] = {}
        self.uses: dict[int, set[str]] = {}

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED_VARIABLES:
            return

        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.defs.setdefault(node.lineno, set()).add(node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            if node.target.id in TRACKED_VARIABLES:
                self.uses.setdefault(node.target.lineno, set()).add(node.target.id)
                self.defs.setdefault(node.target.lineno, set()).add(node.target.id)
        else:
            self.visit(node.target)

        self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for statement in node.body:
            self.visit(statement)

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


def static_def_uses(source_path: Path) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    function = target_function(source_path)
    visitor = DefUseVisitor()
    visitor.visit(function)

    all_args = (
        list(function.args.posonlyargs)
        + list(function.args.args)
        + list(function.args.kwonlyargs)
    )

    if function.args.vararg is not None:
        all_args.append(function.args.vararg)

    if function.args.kwarg is not None:
        all_args.append(function.args.kwarg)

    for argument in all_args:
        if argument.arg in TRACKED_VARIABLES:
            visitor.defs.setdefault(function.lineno, set()).add(argument.arg)

    return visitor.defs, visitor.uses


def parse_trace(
    trace_path: Path, source_path: Path
) -> list[dict[str, int | str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")

    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[int, str]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)

        if match is None:
            continue

        if (
            match.group("func") == TARGET_FUNC
            and match.group("file").replace("\\", "/").endswith(TARGET_FILE)
        ):
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    definitions, uses = static_def_uses(source_path)
    current_defs: dict[str, int] | None = None
    pairs: set[tuple[str, int, int]] = set()
    call_count = 0

    for line_number, event in events:
        if event == "call":
            if current_defs is not None:
                fail("encountered nested target call before prior invocation returned")

            call_count += 1
            current_defs = {
                variable: line_number
                for variable in definitions.get(line_number, set())
            }
            continue

        if current_defs is None:
            continue

        if event == "line":
            for variable in uses.get(line_number, set()):
                if variable not in current_defs:
                    fail(
                        f"use of {variable!r} at line {line_number} has no "
                        "reaching def in invocation"
                    )

                pairs.add((variable, current_defs[variable], line_number))

            for variable in definitions.get(line_number, set()):
                current_defs[variable] = line_number

        if event == "return":
            current_defs = None

    if call_count == 0:
        fail(f"trace contains no call event for {TARGET_FUNC}")

    if current_defs is not None:
        fail("trace ended before the final target invocation returned")

    if not pairs:
        fail("target trace produced no observed def-use pairs")

    return [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    answer = parse_trace(args.trace_log, source_path)
    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": answer},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
