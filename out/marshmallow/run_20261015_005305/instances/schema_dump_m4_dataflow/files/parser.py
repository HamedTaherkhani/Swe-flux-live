#!/usr/bin/env python
"""Trace -> oracle.json for schema_dump_m4_dataflow (M4_DataFlow).

Computes every observed def-use pair (with observation counts) of the local
variables of ``marshmallow.schema.Schema.dump`` aggregated over every
invocation in the traced test run.

The statement structure (which lines each statement spans, which names it
defines and which names it reads on which line) is derived from the target
source via ``ast``; which statements executed, in which order, whether they
completed, and the runtime value of the ``many`` argument are taken from the
trace.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter

TARGET_REL = "src/marshmallow/schema.py"
TARGET_QUALNAME = "marshmallow.schema.Schema.dump"
CLASS_NAME = "Schema"
FUNC_NAME = "dump"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_function(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == FUNC_NAME:
                    return item
    fail(f"could not find {CLASS_NAME}.{FUNC_NAME} in {TARGET_REL}")
    raise AssertionError


class Stmt:
    """A unit of execution: a simple statement, or the test of an ``if``."""

    def __init__(self, start, end, defs, uses, ifexp_guarded):
        self.start = start
        self.end = end
        self.defs = defs  # list of names
        self.uses = uses  # list of (name, line)
        # (name, line) uses that only occur when an IfExp test on ``many``
        # selects the body branch (``self.many if many is None else ...``)
        self.ifexp_guarded = ifexp_guarded


def name_loads(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.append((n.id, n.lineno))
    return out


def build_stmts(func: ast.FunctionDef):
    params = [a.arg for a in func.args.posonlyargs + func.args.args + func.args.kwonlyargs]
    stmts: list[Stmt] = []

    def visit(body):
        for st in body:
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
                continue  # docstring
            if isinstance(st, ast.If):
                stmts.append(Stmt(st.test.lineno, st.test.end_lineno, [], name_loads(st.test), set()))
                visit(st.body)
                visit(st.orelse)
                continue
            if isinstance(st, ast.Assign):
                defs = [t.id for t in st.targets if isinstance(t, ast.Name)]
                value = st.value
            elif isinstance(st, ast.Return):
                defs = []
                value = st.value
            else:
                fail(f"unsupported statement {type(st).__name__} at line {st.lineno}")
            guarded = set()
            if isinstance(value, ast.IfExp):
                guarded = set(name_loads(value.body)) - set(name_loads(value.test)) - set(
                    name_loads(value.orelse)
                )
            stmts.append(Stmt(st.lineno, st.end_lineno, defs, name_loads(value), guarded))

    visit(func.body)
    return params, stmts


def stmt_for_line(stmts, line):
    for s in stmts:
        if s.start <= line <= s.end:
            return s
    return None


def parse_trace(path):
    """Return list of invocations, each {'many': repr, 'events': [(event, line)]}."""
    invocations = []
    stack = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            if m.group("func") != TARGET_QUALNAME:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
                continue
            event = m.group("event")
            line = int(m.group("line"))
            if event == "call":
                mm = re.search(r"'many': '([^']*)'", m.group("rest"))
                if not mm:
                    fail("call event without 'many' local")
                inv = {"many": mm.group(1), "events": []}
                invocations.append(inv)
                stack.append(inv)
                continue
            if not stack:
                fail(f"event outside of an invocation: {raw.strip()}")
            stack[-1]["events"].append((event, line))
            if event == "return":
                stack.pop()
    if stack:
        fail("unterminated invocation(s) in trace")
    return invocations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        fail(f"trace log missing or empty: {args.trace_log}")

    src_path = args.source or os.path.join(os.getcwd(), TARGET_REL)
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = find_function(tree)
    def_line = func.lineno
    params, stmts = build_stmts(func)

    invocations = parse_trace(args.trace_log)
    if not invocations:
        fail("zero events for the target function in the trace")

    counts: Counter = Counter()
    for inv in invocations:
        # ordered list of executed statements (each runs at most once: no loops)
        executed = []
        for event, line in inv["events"]:
            if event != "line":
                continue
            s = stmt_for_line(stmts, line)
            if s is None:
                fail(f"line {line} does not map to a statement")
            if not executed or executed[-1] is not s:
                if s in executed:
                    fail(f"statement at line {s.start} re-entered; unexpected")
                executed.append(s)
        if not executed:
            fail("invocation without executed lines")

        reaching = {p: def_line for p in params}
        for idx, s in enumerate(executed):
            seen = set()
            for name, uline in s.uses:
                if name not in reaching:
                    continue  # globals / builtins
                if (name, uline) in s.ifexp_guarded and inv["many"] != "None":
                    continue
                if (name, uline) in seen:
                    continue
                seen.add((name, uline))
                counts[(name, reaching[name], uline)] += 1
            completed = idx + 1 < len(executed)
            if completed:
                for d in s.defs:
                    reaching[d] = s.start

    answer = [
        {"count": c, "def_line": d, "use_line": u, "variable": v}
        for (v, d, u), c in sorted(counts.items())
    ]

    question = (
        "Test file: `marshmallow_qa/schema_dump_m4_dataflow/files/testcase.py`, test class "
        "`DumpFlowTest`. Run ALL test methods of that class (pytest id "
        "`marshmallow_qa/schema_dump_m4_dataflow/files/testcase.py::DumpFlowTest`; every "
        "method passes). During that run, the method `Schema.dump` in `src/marshmallow/schema.py` "
        "(qualname `marshmallow.schema.Schema.dump`, defined at line "
        f"{def_line}) is invoked many times, both from the test's own entry points and "
        "recursively through nested fields. Consider every invocation (every call of "
        "`Schema.dump`, whatever Schema subclass `self` is, including nested/recursive "
        "ones and invocations that end by raising an exception) across ALL test methods "
        "of the class.\n\n"
        "Report every def-use pair of the function's local variables that was actually "
        "observed at runtime, together with how many times it was observed.\n\n"
        "Definitions:\n"
        "- Tracked variables: the local names of `Schema.dump`, i.e. the parameters "
        "`self`, `obj`, `many` and every name assigned in the body. Globals and builtins "
        "(e.g. `PRE_DUMP`, `POST_DUMP`, `bool`) are not tracked. Attribute accesses are "
        "uses of the base name only (e.g. `self.x` is a use of `self`).\n"
        "- Defs: every parameter is defined at the `def` line of the function (line "
        f"{def_line}). A plain assignment `x = ...` defines `x` at the line where that "
        "assignment statement begins, and the def takes effect only if the statement "
        "completes; if the right-hand side raises, the variable is not (re)defined.\n"
        "- Uses: a read of a tracked name. The use line is the absolute 1-based line in "
        "`src/marshmallow/schema.py` on which that name token appears (for a statement "
        "spanning several lines, a name written on a continuation line is used on that "
        "continuation line, not on the statement's first line). The test of an `if` is a "
        "use site; the `return` expression is a use site. Only operands that are actually "
        "evaluated count: in a conditional expression `a if cond else b`, the names in the "
        "branch not taken are NOT used. Uses in a statement count even if the statement "
        "later raises, provided they are evaluated before the exception (all arguments of a "
        "call are evaluated before the callee runs). Within one assignment, the right-hand "
        "side uses happen before the left-hand side def.\n"
        "- Observation: one execution of a statement, within one invocation, that reads "
        "variable V on line U while the reaching (most recent, completed) def of V in that "
        "same invocation is at line D, adds 1 to the count of (V, D, U). If the same name "
        "appears more than once on the same line within one execution of a statement "
        "(e.g. `f(x, key=x)` on one line), that is ONE observation. Each invocation has its "
        "own frame: defs never flow between different invocations (e.g. between an outer "
        "call and a nested call).\n"
        "- `count` is the total number of observations of that exact (variable, def_line, "
        "use_line) triple summed over all invocations in all test methods of the class.\n\n"
        "Output: a JSON object `{\"observed_def_use_pairs\": [...]}` where each element is "
        "`{\"count\": int, \"def_line\": int, \"use_line\": int, \"variable\": str}`; "
        "`variable` is the bare variable name (e.g. `\"x\"`), line numbers are JSON integers. "
        "Include only triples with count >= 1; each (variable, def_line, use_line) triple "
        "appears exactly once (the count carries the multiplicity). Sort ascending by "
        "variable (plain string comparison), then def_line, then use_line."
    )

    oracle = {
        "question_kind": "M4_DataFlow",
        "question": question,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": answer},
    }
    if not answer:
        fail("computed an empty answer")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=1))
    print(f"invocations: {len(invocations)}  pairs: {len(answer)}")


if __name__ == "__main__":
    main()
