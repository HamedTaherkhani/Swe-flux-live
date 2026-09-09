#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "flask.helpers.get_root_path"
TARGET_FILE = "src/flask/helpers.py"
TARGET_FILE_SUFFIX = f"/{TARGET_FILE}"
TRACKED_VARIABLES = {"filepath", "import_name", "loader", "mod", "spec"}

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/helpers_get_root_path_s4_dataflow/files/testcase.py::"
    "TestGetRootPathDataFlow::test_generated_module_scenarios`. Across all "
    "runtime invocations of `flask.helpers.get_root_path` in "
    "`src/flask/helpers.py` during that test, what are all unique observed "
    "def-use pairs for exactly these local variables: `filepath`, "
    "`import_name`, `loader`, `mod`, and `spec`? A def is a successful runtime "
    "binding produced by parameter binding or an assignment target; each "
    "parameter is defined on the function's `def` line on every call. A use "
    "is a runtime read of that variable's current value on a source line in "
    "the target function's own frame. A pair is observed when the value from "
    "that def reaches that use without an intervening def of the same variable "
    "in that invocation. Definitions never reach across invocations. An "
    "invocation is one call of the target function during this test run, "
    "numbered from 1 in chronological call-entry order, although invocation "
    "numbers are not included in the answer. For augmented assignment such as "
    "`x += 1`, treat the line first as a use of the old reaching def and then "
    "as a new def of `x` on that same line. A `for x in values` loop header "
    "defines `x` anew on every iteration before the body executes. "
    "Comprehension-local and generator-expression-local bindings belong to "
    "their implicit separate frames and are excluded, even if their spelling "
    "matches a tracked variable; reads performed in those implicit frames, "
    "including reads of outer variables, are also excluded. Count reads only "
    "when runtime evaluation actually reaches them, so a short-circuited "
    "operand is not a use. Source line numbers are absolute, 1-based line "
    "numbers in the named file as it exists in the repository. For a "
    "multi-line statement or expression, `def_line` is the line where its "
    "assignment target begins and `use_line` is the line containing the "
    "evaluated variable read; the function `def` line can therefore appear "
    "for parameter definitions, while decorator and docstring lines are not "
    "definitions or uses. Return a JSON object with exactly one key, "
    "`observed_def_use_pairs`, whose value is a JSON list of objects. Every "
    "object has exactly the keys `def_line` (JSON integer), `use_line` (JSON "
    "integer), and `variable` (JSON string). Remove duplicate objects produced "
    "by repeated reads or invocations, then sort the list by `variable` in "
    "ascending Unicode lexicographic order, then by `def_line` ascending, then "
    "by `use_line` ascending. The object keys are serialized in ascending "
    "lexicographic order; no `repr` or `str` formatting, null sentinel, "
    "function-name normalization, or exception-name formatting applies "
    "because the only reported values are the variable spelling and integer "
    "source lines."
)


def fail(message: str) -> None:
    raise RuntimeError(message)


class TargetFrameNames(ast.NodeVisitor):
    def __init__(self, target: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.target = target
        self.uses: dict[int, set[str]] = {}
        self.definitions: dict[int, set[str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.target:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.target:
            self.generic_visit(node)

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

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED_VARIABLES:
            return

        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.definitions.setdefault(node.lineno, set()).add(node.id)


def source_dataflow(
    source_path: Path,
) -> tuple[int, dict[int, set[str]], dict[int, set[str]]]:
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "get_root_path"
        ),
        None,
    )

    if target is None:
        fail("could not locate target function in source")

    names = TargetFrameNames(target)
    names.visit(target)
    return target.lineno, names.uses, names.definitions


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()
    trace_path = Path(args.trace_log)

    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

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
            and match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX)
        ):
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    def_line, uses_by_line, definitions_by_line = source_dataflow(
        Path.cwd() / TARGET_FILE
    )
    pairs: set[tuple[str, int, int]] = set()
    reaching_defs: dict[str, int] | None = None
    call_count = 0

    for line_number, event in events:
        if event == "call":
            if reaching_defs is not None:
                fail("overlapping target invocations are not supported")

            call_count += 1
            reaching_defs = {"import_name": def_line}
            continue

        if reaching_defs is None:
            fail("target event occurred outside an invocation")

        if event == "line":
            for variable in sorted(uses_by_line.get(line_number, ())):
                if variable not in reaching_defs:
                    fail(
                        f"use of {variable} on line {line_number} has no reaching def"
                    )

                pairs.add((variable, reaching_defs[variable], line_number))

            for variable in sorted(definitions_by_line.get(line_number, ())):
                reaching_defs[variable] = line_number
        elif event == "return":
            reaching_defs = None

    if call_count == 0:
        fail(f"trace has target events but no call event for {TARGET_FUNC}")

    if reaching_defs is not None:
        fail(f"final invocation of {TARGET_FUNC} has no return event")

    if not pairs:
        fail("no observed def-use pairs were computed")

    observed = [
        {"def_line": def_line_value, "use_line": use_line, "variable": variable}
        for variable, def_line_value, use_line in sorted(pairs)
    ]
    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": observed},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
