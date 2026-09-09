from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/_compat/shared.py"
TARGET_FUNC = "fastapi._compat.shared.field_annotation_is_scalar_sequence"
TRACKED = (
    "annotation",
    "arg",
    "at_least_one_scalar_sequence",
    "origin",
)

QUESTION = """Run the pytest test `fastapi_qa/shared_field_annotation_is_scalar_sequence_s4_dataflow/files/testcase.py::TestScalarSequenceDataFlow::test_generated_annotation_families` and consider every invocation of `fastapi._compat.shared.field_annotation_is_scalar_sequence` in `fastapi/_compat/shared.py`, including recursive invocations. What are all unique runtime-observed def-use pairs for the local variables `annotation`, `arg`, `at_least_one_scalar_sequence`, and `origin`?

A definition ("def") is a parameter binding or a completed assignment to that local in one invocation's frame. Parameters are defined on the function's `def` line for each invocation. A use is an actually evaluated read of that local in the same frame on the source line containing the read; a definition reaches such a use only if no later definition of that local has completed in that frame. Process reads on a line before definitions completed by that line. Thus an augmented assignment such as `total += delta` is both a use of `total` reached by its old definition and a new definition of `total` on that line. Each successful iteration of a `for x in values` loop redefines `x` on the loop-header line after the iterable/header reads and before the body executes.

Comprehension iteration variables are local to the comprehension's generated frame and are excluded. Reads evaluated in a comprehension-generated frame are also excluded, while any expression that Python evaluates in the target function's own frame to create the comprehension's outermost iterable is included. Definitions and uses never cross invocation frames. An invocation means one call of the target function, with calls ordered chronologically and numbered from 1 if reconstructing the run; invocation numbers are not included in the answer.

Line numbers are absolute 1-based source line numbers in `fastapi/_compat/shared.py` as it exists in the repository. For a multi-line statement or expression, attribute each def or use to the physical source line on which that assignment target or variable read begins; the function `def` line can therefore appear for parameter definitions, while decorator and docstring lines do not count. Include only activity in frames whose exact fully qualified name is `fastapi._compat.shared.field_annotation_is_scalar_sequence`; do not include similarly named functions, callees, or comprehension-generated frames.

Return a JSON object with exactly one key, `observed_def_use_pairs`. Its value is a list of objects, each having exactly `def_line` (integer), `use_line` (integer), and `variable` (string). Remove duplicate triples observed across iterations or invocations, then sort the objects by `variable`, then `def_line`, then `use_line`, all ascending (strings lexicographically and integers numerically)."""


class LineFacts(ast.NodeVisitor):
    def __init__(self) -> None:
        self.uses: dict[int, set[str]] = {}
        self.defs: dict[int, set[str]] = {}

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defs.setdefault(node.lineno, set()).add(node.id)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        # The outermost iterable is created in the containing frame. The
        # remaining expression executes in the generator's separate frame.
        if node.generators:
            self.visit(node.generators[0].iter)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        if node.generators:
            self.visit(node.generators[0].iter)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        if node.generators:
            self.visit(node.generators[0].iter)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        if node.generators:
            self.visit(node.generators[0].iter)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "field_annotation_is_scalar_sequence":
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return


def source_facts(root: Path) -> tuple[dict[int, set[str]], dict[int, set[str]], int]:
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source file is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "field_annotation_is_scalar_sequence"
        ),
        None,
    )
    if target is None:
        raise RuntimeError("target function was not found in target source")
    facts = LineFacts()
    facts.visit(target)
    return facts.uses, facts.defs, target.lineno


EVENT_RE = re.compile(
    r"(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def compute_pairs(trace_path: Path, root: Path) -> list[dict[str, int | str]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    uses_by_line, defs_by_line, parameter_line = source_facts(root)
    frames: list[dict[str, int]] = []
    pairs: set[tuple[str, int, int]] = set()
    target_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))

        if event == "call":
            frames.append({"annotation": parameter_line})
            continue
        if not frames:
            raise RuntimeError(
                f"target {event} event at line {line} has no active target frame"
            )
        if event == "line":
            reaching_defs = frames[-1]
            for variable in sorted(uses_by_line.get(line, ())):
                if variable not in reaching_defs:
                    raise RuntimeError(
                        f"use of {variable!r} at line {line} has no reaching definition"
                    )
                pairs.add((variable, reaching_defs[variable], line))
            for variable in sorted(defs_by_line.get(line, ())):
                reaching_defs[variable] = line
        elif event == "return":
            frames.pop()

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for exact target function {TARGET_FUNC}"
        )
    if frames:
        raise RuntimeError(f"trace ended with {len(frames)} unterminated target frame(s)")
    if not pairs:
        raise RuntimeError("target events produced no observed def-use pairs")

    return [
        {"def_line": def_line, "use_line": use_line, "variable": variable}
        for variable, def_line, use_line in sorted(pairs)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    answer = {"observed_def_use_pairs": compute_pairs(args.trace_log, root)}
    payload = {
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
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(answer, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

