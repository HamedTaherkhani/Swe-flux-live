from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/add_latest_release_date.py"
TARGET_FUNC = "scripts.add_latest_release_date.main"
TRACKED = ("date_part", "f", "i", "line", "lines", "match", "today", "version")

QUESTION = """Run the pytest test `fastapi_qa/add_latest_release_date_main_m4_dataflow/files/testcase.py::TestAddLatestReleaseDateDataFlow::test_generated_release_note_variants` and consider every invocation of the exact function `scripts.add_latest_release_date.main` in `scripts/add_latest_release_date.py`. Across those invocations, what are all unique runtime-observed def-use pairs for exactly these local variables: `date_part`, `f`, `i`, `line`, `lines`, `match`, `today`, and `version`?

A definition ("def") is a parameter binding, a completed assignment to a local, a completed `with ... as` binding, or a successful `for`-target binding in one invocation's frame. Parameters, if tracked, are defined on the function's `def` line for each invocation. A use is an actually evaluated read of a tracked local in that same target frame, attributed to the physical source line where the variable read begins. A definition reaches a use only when it is the most recently completed definition of that variable in the same invocation at the time of the read. On a line that both reads and defines a variable, process all reads before the line's definitions. Consequently, an augmented assignment such as `total += delta` is a use of the old `total` followed by a new definition of `total` on that line.

For a `for x in values` statement, reading `values` is a use on the loop-header line, and each successful iteration defines `x` on that same line before the body executes; terminal iterator exhaustion is not a definition. Each pass that successfully binds the loop target is one iteration, numbered from 1 in execution order if reconstructing the run, but iteration numbers are not emitted. Comprehension iteration variables and all reads performed in comprehension-generated frames are excluded; only evaluation performed in the target function's own frame counts. Definitions and uses never cross invocation frames. An invocation is one `call` of the target function during the test run; invocations are numbered from 1 in chronological order if reconstructing execution, but invocation numbers are not emitted.

Include only activity in frames whose exact fully qualified name is `scripts.add_latest_release_date.main`; exclude callees, similarly named functions, and generated comprehension frames. Line numbers are absolute 1-based physical line numbers in `scripts/add_latest_release_date.py` as it exists in the repository. For a multi-line statement or expression, use the physical line where the relevant assignment target or variable read begins. The function `def` line can appear only for tracked parameter definitions; decorator and docstring lines do not count.

Return a JSON object with exactly one key, `observed_def_use_pairs`. Its value is a list of objects, each with exactly three keys: `def_line` as a JSON integer, `use_line` as a JSON integer, and `variable` as a JSON string containing the local's exact source spelling. No value is represented with `repr`, `str`, or JSON null because the answer contains only source spellings and line-number integers. Remove duplicate `(variable, def_line, use_line)` triples across all iterations and invocations. Sort the objects by `variable` lexicographically ascending, then `def_line` numerically ascending, then `use_line` numerically ascending."""


class LineFacts(ast.NodeVisitor):
    def __init__(self, target_name: str) -> None:
        self.target_name = target_name
        self.uses: dict[int, set[str]] = {}
        self.defs: dict[int, set[str]] = {}

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in TRACKED:
            return
        if isinstance(node.ctx, ast.Load):
            self.uses.setdefault(node.lineno, set()).add(node.id)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defs.setdefault(node.lineno, set()).add(node.id)

    def _visit_outermost_iterable(self, node: ast.AST) -> None:
        generators = getattr(node, "generators", ())
        if generators:
            self.visit(generators[0].iter)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_outermost_iterable(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_outermost_iterable(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_outermost_iterable(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_outermost_iterable(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == self.target_name:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return


def source_facts(
    root: Path,
) -> tuple[dict[int, set[str]], dict[int, set[str]], int, set[str]]:
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source file is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ),
        None,
    )
    if target is None:
        raise RuntimeError("target function was not found in target source")

    facts = LineFacts(target.name)
    facts.visit(target)
    parameters = {
        argument.arg
        for argument in (
            target.args.posonlyargs + target.args.args + target.args.kwonlyargs
        )
        if argument.arg in TRACKED
    }
    if target.args.vararg and target.args.vararg.arg in TRACKED:
        parameters.add(target.args.vararg.arg)
    if target.args.kwarg and target.args.kwarg.arg in TRACKED:
        parameters.add(target.args.kwarg.arg)
    return facts.uses, facts.defs, target.lineno, parameters


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

    uses_by_line, defs_by_line, parameter_line, parameters = source_facts(root)
    frames: list[dict[str, int]] = []
    pairs: set[tuple[str, int, int]] = set()
    target_events = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            frames.append({variable: parameter_line for variable in parameters})
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
