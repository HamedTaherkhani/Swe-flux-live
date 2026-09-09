from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FUNC = "sqlglot.parsers.mysql.MySQLParser._parse_show_mysql"
TRACKED_VARIABLES = (
    "channel",
    "db",
    "for_group",
    "for_role",
    "for_table",
    "for_user",
    "full",
    "global_",
    "index",
    "into_outfile",
    "json",
    "like",
    "limit",
    "log",
    "offset",
    "position",
    "query",
    "target",
    "target_id",
    "this",
    "types",
    "where",
)
PARAMETERS = ("this", "target", "full", "global_")
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run all test methods defined on `TestMySQLShowDataFlow` in
`sqlglot_qa/mysql_parse_show_mysql_m4_dataflow/files/testcase.py`, as selected
by the pytest id
`sqlglot_qa/mysql_parse_show_mysql_m4_dataflow/files/testcase.py::TestMySQLShowDataFlow`.
The answer aggregates observations over every `def test_...` method in that
class and every invocation those methods cause of
`sqlglot.parsers.mysql.MySQLParser._parse_show_mysql` in
`sqlglot/parsers/mysql.py`. A target invocation is one call of that function,
numbered from 1 in chronological call order across the complete pytest run.
Counts are totals across all test methods and all target invocations; the
invocation number itself is not reported.

Track exactly these target-frame local variables: `channel`, `db`, `for_group`,
`for_role`, `for_table`, `for_user`, `full`, `global_`, `index`,
`into_outfile`, `json`, `like`, `limit`, `log`, `offset`, `position`, `query`,
`target`, `target_id`, `this`, `types`, and `where`. Do not track `self`,
`mutex`, attributes, globals, or locals in called functions.

A definition ("def") is a parameter binding or a completed assignment to a
tracked local in the target frame. The parameters `this`, `target`, `full`,
and `global_` are defined on the function's `def` line at each call. A use is
accounted at line level: if an executed source line contains one or more
`ast.Load` occurrences of a tracked target-frame name, that execution
contributes exactly one use observation for that variable. Thus, multiple
syntactic reads of the same variable on one source line count once, while the
same line executed repeatedly contributes once per execution. Reads or writes
in callees do not count.

For each use observation, pair its use line with the most recent definition of
that variable in the same invocation, provided no intervening definition has
killed it. An observed pair is the triple `(variable, def_line, use_line)`
produced by one such reaching-definition event. The `count` for a triple is
how many times that exact event occurs, summed across the whole class run.
Pairs never observed are absent.

Use Python evaluation order for a source line: reads are paired before writes
on that line update the reaching definition. Consequently, augmented
assignment such as `x += 1` is both a use of the old definition and a new
definition on that line. For `for x in iterable`, reads needed to evaluate the
iterable occur first and each successful loop-header execution then defines
`x`; an exhausted check does not define it. An iteration is the Nth execution
of the loop header that successfully binds its target, although no iteration
number is reported. Comprehension iteration variables are local to their
comprehension scope: each successful iteration defines that
comprehension-local name, reads of it count only in that scope, and it neither
defines nor uses a same-spelled local in the target frame.

Line numbers are absolute 1-based line numbers in `sqlglot/parsers/mysql.py`
as it exists in the repository. For a multi-line statement or expression,
attribute each name to the source line on which its specific name-bearing AST
expression begins; a line contributes only when that source line executes.
Assignment definitions use the line on which the assignment target begins.
The function's `def` line can appear for parameter definitions; decorator and
docstring lines do not count.

Return exactly one JSON object with the key `observed_def_use_pairs`. Its value
is a list of objects having exactly `count` (integer), `def_line` (integer),
`use_line` (integer), and `variable` (string). Variable strings are the exact
Python identifiers listed above; integers are ordinary base-10 JSON integers,
and no value is represented by `null`, `repr()`, or `str()`. Emit one row per
unique triple: multiplicity exists only in `count`, so duplicate rows are
forbidden. Sort rows by `variable`, then `def_line`, then `use_line`, all
ascending; these three fields uniquely determine a row."""


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
    parser_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MySQLParser"
    )
    target = next(
        node
        for node in parser_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_show_mysql"
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
    counts: Counter[tuple[str, int, int]] = Counter()

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
                counts[(variable, reaching[variable], line)] += 1
            for variable in sorted(writes.get(line, ())):
                reaching[variable] = line
        elif event == "return":
            invocation_stack.pop()

    if invocation_stack:
        raise RuntimeError("trace ended during a target invocation")

    return [
        {
            "count": count,
            "def_line": definition,
            "use_line": use,
            "variable": variable,
        }
        for (variable, definition, use), count in sorted(counts.items())
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    source_path = root / "sqlglot" / "parsers" / "mysql.py"
    def_line, reads, writes = source_accesses(source_path)
    answer = {
        "observed_def_use_pairs": compute_pairs(
            parse_events(args.trace_log), def_line, reads, writes
        )
    }
    if not answer["observed_def_use_pairs"]:
        raise RuntimeError("computed answer has no observed def-use pairs")

    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
