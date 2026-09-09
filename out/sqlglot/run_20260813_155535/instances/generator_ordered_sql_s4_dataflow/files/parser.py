from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "sqlglot.generator.Generator.ordered_sql"
TRACKED_VARIABLES = (
    "ancestor",
    "asc",
    "desc",
    "expression",
    "null_sort_order",
    "nulls_are_large",
    "nulls_are_last",
    "nulls_are_small",
    "nulls_first",
    "nulls_last",
    "nulls_sort_change",
    "resolved",
    "self",
    "sort_order",
    "spec",
    "target",
    "this",
    "window",
    "window_this",
    "with_fill",
)
PARAMETERS = ("expression", "self")
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test
`sqlglot_qa/generator_ordered_sql_s4_dataflow/files/testcase.py::TestGeneratorOrderedDataFlow::test_seeded_ordering_contexts`
and consider every invocation of `sqlglot.generator.Generator.ordered_sql` in
`sqlglot/generator.py` caused by that test. An invocation is one call of that
function, numbered from 1 in chronological call order; aggregate observations
across all invocations. The invocation number itself is not reported.

For each of these local variable names exactly: `ancestor`, `asc`, `desc`,
`expression`, `null_sort_order`, `nulls_are_large`, `nulls_are_last`,
`nulls_are_small`, `nulls_first`, `nulls_last`, `nulls_sort_change`,
`resolved`, `self`, `sort_order`, `spec`, `target`, `this`, `window`,
`window_this`, and `with_fill`, report every unique runtime-observed def-use
pair. Do not track attributes, globals, or locals in called functions.

A definition ("def") is a parameter binding or a completed assignment to a
tracked local in the target frame. The parameters `self` and `expression`
count as definitions on the function's `def` line at each call. A use is
accounted at line level: when an executed source line contains one or more
reads of a tracked target-frame name, that execution observes one use for
that variable on that line. Multiple syntactic reads of the same variable on
one line still constitute one line-level use. A pair `{variable, def_line,
use_line}` is observed when the value established by that definition reaches
that use without an intervening definition of the same local. Definitions
and uses in callees do not count.

Use Python evaluation order: reads needed by an assignment occur before that
assignment's definition. Augmented assignment such as `x += 1` is both a use
of the old reaching definition and a new definition on that same line. A
`for x in iterable` header reads the iterable first and redefines `x` once
for each successful iteration; the final exhausted check does not redefine
`x`. Comprehension iteration variables are comprehension-local: each
successful iteration defines that comprehension-local name, its reads count
only inside the comprehension frame or scope, and it neither defines nor uses
a same-spelled local in the target frame.

Line numbers are absolute 1-based source line numbers in
`sqlglot/generator.py` as it exists in the repository. For a multi-line
statement or expression, attribute each read or definition to the source line
on which that specific name-bearing expression or assignment begins; the
runtime execution of a component is identified by execution of that line.
Assignment definitions use the line on which the assignment target begins.
The function's `def` line can appear for parameter definitions; decorator and
docstring lines do not count.

Return exactly one JSON object with key `observed_def_use_pairs`. Its value is
a list of objects with exactly the keys `def_line` (integer), `use_line`
(integer), and `variable` (string). Variable strings are the exact Python
identifiers listed above, and line numbers are ordinary base-10 JSON
integers; no reported value uses `repr()`, `str()`, an empty string, or JSON
`null`. Remove duplicate triples even if they are observed in different
invocations or multiple times in one invocation. Sort the list by `variable`,
then `def_line`, then `use_line`, all ascending; those fields are the complete
tie-break order."""


class NameAccesses(ast.NodeVisitor):
    def __init__(self) -> None:
        self.reads: dict[int, set[str]] = {}
        self.writes: dict[int, set[str]] = {}

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in TRACKED_VARIABLES:
            destination = self.reads if isinstance(node.ctx, ast.Load) else self.writes
            destination.setdefault(node.lineno, set()).add(node.id)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id in TRACKED_VARIABLES:
            self.reads.setdefault(node.target.lineno, set()).add(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def source_accesses(source_path: Path) -> tuple[int, dict[int, set[str]], dict[int, set[str]]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    generator_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Generator"
    )
    target = next(
        node
        for node in generator_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "ordered_sql"
    )

    accesses = NameAccesses()
    for statement in target.body:
        accesses.visit(statement)
    return target.lineno, accesses.reads, accesses.writes


def parse_events(trace_path: Path) -> list[tuple[int, str]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events: list[tuple[int, str]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.match(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event == "call" for _, event in events):
        raise RuntimeError(f"trace contains no call event for {TARGET_FUNC}")
    return events


def compute_pairs(
    events: list[tuple[int, str]],
    def_line: int,
    reads: dict[int, set[str]],
    writes: dict[int, set[str]],
) -> list[dict[str, int | str]]:
    invocation_stack: list[dict[str, int]] = []
    pairs: set[tuple[str, int, int]] = set()

    for line, event in events:
        if event == "call":
            invocation_stack.append({variable: def_line for variable in PARAMETERS})
            continue

        if not invocation_stack:
            raise RuntimeError(f"target {event} event encountered outside an invocation")
        reaching = invocation_stack[-1]

        if event == "line":
            for variable in sorted(reads.get(line, ())):
                if variable not in reaching:
                    raise RuntimeError(
                        f"use of {variable!r} on line {line} has no reaching definition"
                    )
                pairs.add((variable, reaching[variable], line))
            for variable in sorted(writes.get(line, ())):
                reaching[variable] = line
        elif event == "return":
            invocation_stack.pop()

    if invocation_stack:
        raise RuntimeError("trace ended during a target invocation")

    return [
        {"def_line": definition, "use_line": use, "variable": variable}
        for variable, definition, use in sorted(pairs)
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    source_path = root / "sqlglot" / "generator.py"
    def_line, reads, writes = source_accesses(source_path)
    answer = {
        "observed_def_use_pairs": compute_pairs(
            parse_events(args.trace_log), def_line, reads, writes
        )
    }
    if not answer["observed_def_use_pairs"]:
        raise RuntimeError("computed answer has no observed def-use pairs")

    payload = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
