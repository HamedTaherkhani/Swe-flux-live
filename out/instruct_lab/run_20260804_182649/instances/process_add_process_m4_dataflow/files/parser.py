from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/instructlab/process/process.py"
TARGET_FUNC = "instructlab.process.process.add_process"
TRACKED = (
    "children_pids",
    "cmd",
    "extra_imports",
    "kwargs",
    "local_uuid",
    "log",
    "log_dir",
    "log_file",
    "pid",
    "process_mode",
    "process_registry",
    "process_type",
    "target",
)

QUESTION = """Run only the pytest test `instruct_lab_qa/process_add_process_m4_dataflow/files/testcase.py::TestAddProcessDataFlow::test_generated_mode_and_startup_matrix`. During that complete test run, consider every invocation of `instructlab.process.process.add_process` in `src/instructlab/process/process.py`; an invocation is one `call` of that function, numbered 1-based in chronological order. Report the union across all invocations of all unique observed dynamic def-use pairs for exactly these target-frame local variables: `children_pids`, `cmd`, `extra_imports`, `kwargs`, `local_uuid`, `log`, `log_dir`, `log_file`, `pid`, `process_mode`, `process_registry`, `process_type`, and `target`.

A def is a binding of one of those local variables that actually occurs in the target function's own frame, either a completed assignment, a `with ... as name` binding, or a parameter binding. Every parameter, including the `kwargs` variadic keyword parameter, is defined at the function's `def` line. A use is a read of that local variable by an executed expression in that same target-function frame. A pair is `{variable, def_line, use_line}` when the value from that def reaches that use before any intervening def of the same variable in the same invocation. Process reads on a source line before bindings made by that line. Thus an augmented assignment such as `x += 1` first uses the old reaching def of `x` and then creates a new def of `x` on that line. A `for x in iterable` header reads target-frame variables in `iterable` and creates a new def of `x` on every iteration; iteration N means the Nth time that loop header binds its target. Binding an attribute or subscript such as `obj.value` or `obj[key]` does not redefine `obj`. For a comprehension, its outermost iterable expression is evaluated in the containing target frame, so reads in that expression count; comprehension-local bindings and reads that execute in the comprehension's separate frame are excluded.

Use absolute 1-based source line numbers in the named repository file as it exists for this run. For a multi-line statement or expression, use the source line on which the relevant variable-bearing expression begins and only count it if that line executes. The function `def` line can therefore appear for parameter defs; decorator and docstring lines do not count as uses or assignment defs. Include only reads and bindings executed by the target function's own frame: events in callees are excluded. Include only pairs produced within one invocation and never carry a reaching def between invocations. Exception events do not themselves define or use variables, and a return event only ends its invocation. If the same triple is observed repeatedly, including across invocations, emit it once.

Return exactly one JSON object with key `observed_def_use_pairs`. Its value is a list of objects having exactly the keys `def_line` (JSON integer), `use_line` (JSON integer), and `variable` (JSON string containing the source identifier exactly). Sort the list by `variable`, then `def_line`, then `use_line`, all ascending; this is the complete tie-break order. Do not apply `repr()` or `str()` formatting to line numbers or variable names."""


class LineFacts(ast.NodeVisitor):
    def __init__(self, tracked: set[str]) -> None:
        self.tracked = tracked
        self.uses: dict[int, set[str]] = {}
        self.defs: dict[int, set[str]] = {}

    def _add(self, table: dict[int, set[str]], line: int, name: str) -> None:
        if name in self.tracked:
            table.setdefault(line, set()).add(name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._add(self.uses, node.lineno, node.id)
        elif isinstance(node.ctx, ast.Store):
            self._add(self.defs, node.lineno, node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._add(self.uses, node.target.lineno, node.target.id)
            self._add(self.defs, node.target.lineno, node.target.id)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for statement in node.body:
            self.visit(statement)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def _visit_comprehension(self, generators: list[ast.comprehension]) -> None:
        if generators:
            self.visit(generators[0].iter)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators)


def source_facts(source_path: Path) -> tuple[int, set[str], LineFacts]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "add_process"
        ),
        None,
    )
    if function is None:
        raise RuntimeError(f"target function not found in {source_path}")

    parameters = {
        arg.arg
        for arg in (
            function.args.posonlyargs
            + function.args.args
            + function.args.kwonlyargs
        )
    }
    if function.args.vararg:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg:
        parameters.add(function.args.kwarg.arg)

    facts = LineFacts(set(TRACKED))
    facts.visit(function)
    return function.lineno, parameters.intersection(TRACKED), facts


def trace_events(trace_path: Path) -> list[tuple[int, str]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    pattern = re.compile(
        r"(?P<file>\S+):(?P<line>\d+)\s+"
        + re.escape(TARGET_FUNC)
        + r"\s+event=(?P<event>call|line|return|exception)\b"
    )
    events: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        match = pattern.search(raw_line)
        if match and match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not any(event == "call" for _, event in events):
        raise RuntimeError(f"trace contains no call event for {TARGET_FUNC}")
    return events


def compute_pairs(
    events: list[tuple[int, str]],
    def_line: int,
    parameters: set[str],
    facts: LineFacts,
) -> list[dict[str, int | str]]:
    pairs: set[tuple[str, int, int]] = set()
    reaching: dict[str, int] | None = None

    for line, event in events:
        if event == "call":
            if reaching is not None:
                raise RuntimeError("overlapping target invocations are unsupported")
            reaching = {name: def_line for name in parameters}
            continue
        if event == "return":
            reaching = None
            continue
        if event != "line" or reaching is None:
            continue

        for name in facts.uses.get(line, ()):
            if name in reaching:
                pairs.add((name, reaching[name], line))
        for name in facts.defs.get(line, ()):
            reaching[name] = line

    if reaching is not None:
        raise RuntimeError("trace ended before the target invocation returned")
    if not pairs:
        raise RuntimeError("target events produced no observed def-use pairs")

    return [
        {"def_line": def_at, "use_line": use_at, "variable": name}
        for name, def_at, use_at in sorted(pairs)
    ]


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        root = Path(__file__).resolve().parents[3]
        def_line, parameters, facts = source_facts(root / TARGET_FILE)
        answer = {
            "observed_def_use_pairs": compute_pairs(
                trace_events(args.trace_log), def_line, parameters, facts
            )
        }
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
        print(json.dumps(answer, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
