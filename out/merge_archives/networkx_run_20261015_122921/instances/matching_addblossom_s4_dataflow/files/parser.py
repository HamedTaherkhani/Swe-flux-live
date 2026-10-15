#!/usr/bin/env python
"""Derive dynamic def-use pairs of addBlossom from a line-level trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "networkx/algorithms/matching.py"
FUNC_SUFFIX = ".max_weight_matching.<locals>.addBlossom"
TRACKED = ("bv", "bw", "k", "v", "w")

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")

QUESTION = (
    "Run the pytest test "
    "`networkx_qa/matching_addblossom_s4_dataflow/files/testcase.py::TestAddBlossomDataFlow::test_blossoms_on_random_graphs` "
    "(the only test method in class `TestAddBlossomDataFlow`). During this test, consider every invocation of the nested "
    "function `addBlossom` defined inside `networkx.algorithms.matching.max_weight_matching` (qualname "
    "`max_weight_matching.<locals>.addBlossom`) in `networkx/algorithms/matching.py`; an invocation is one call of that "
    "function, and all invocations are aggregated. Track exactly these local variables of addBlossom: `bv`, `bw`, `k`, `v`, `w`.\n\n"
    "Definitions:\n"
    "- A DEF of a variable happens when a value is bound to that name in addBlossom's own scope: the parameters `v` and `w` "
    "are defined at the `def addBlossom(...)` line on each invocation; an assignment statement (including tuple-unpacking "
    "targets) defines its targets; a `for` loop header defines its target variable once for every element it actually binds "
    "(the final, exhausting check binds nothing and defines nothing).\n"
    "- A USE of a variable happens when an executed statement reads that name (any load of the bare name, including as the "
    "object of an attribute access, subscript, call argument, or the receiver of an attribute/subscript store such as "
    "`x.attr = ...`). A `while` header reads its condition every time the condition is evaluated (including the final false "
    "evaluation). Within one statement, reads happen before the statement's own bindings (e.g. `x = f(x)` uses the previous "
    "def of x and then creates a new def). Every tracked name that syntactically appears as a read in an executed statement "
    "counts as used, regardless of short-circuit evaluation. Augmented assignment (`x += 1`) would count as both a use of the "
    "old def and a new def on that line (none occur on tracked variables here).\n"
    "- Comprehensions: variables bound by a comprehension's own `for` clauses are comprehension-local; they are a different "
    "scope, so they are neither defs nor uses of the function's tracked variables (even if they share a name such as `v` or "
    "`w`). Reads inside a comprehension of a tracked variable from addBlossom's scope (one not bound by that comprehension) "
    "DO count as uses of the function's variable.\n"
    "- Line numbers are absolute 1-based line numbers in `networkx/algorithms/matching.py` as it exists in the repository. "
    "For a statement spanning several physical lines, both its uses and its defs are reported at the line where the "
    "statement begins (e.g. a multi-line `assert` or `nblist = [ ... ]` is reported at its first line). For `if`/`while`/`for` "
    "headers, the line is the line of the `if`/`while`/`for` keyword. The parameter def line is the line of the `def` keyword.\n\n"
    "A def-use pair (variable, def_line, use_line) is OBSERVED if, in at least one invocation, the value bound at def_line is "
    "read at use_line before that variable is rebound. Report each distinct observed triple exactly once (deduplicated across "
    "all invocations and loop iterations). Only report pairs that actually occurred at runtime.\n\n"
    "Answer format: a JSON object with key `observed_def_use_pairs` whose value is a list of objects with keys `variable` "
    "(string, the bare variable name, e.g. \"x\"), `def_line` (integer) and `use_line` (integer), sorted ascending by "
    "`variable` (plain string comparison), then by `def_line`, then by `use_line`."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_target(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "max_weight_matching":
            for sub in ast.walk(node):
                if isinstance(sub, ast.FunctionDef) and sub.name == "addBlossom":
                    return sub
    fail("addBlossom not found in source")


def names_in(node, ctx_type):
    """Tracked names with the given ctx inside node, skipping comprehension-bound names."""
    out = set()

    def visit(n, bound):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            inner = set(bound)
            for gen in n.generators:
                # the first iterable is evaluated in the enclosing scope
                visit(gen.iter, bound if gen is n.generators[0] else inner)
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        inner.add(t.id)
                for cond in gen.ifs:
                    visit(cond, inner)
            elts = [n.key, n.value] if isinstance(n, ast.DictComp) else [n.elt]
            for e in elts:
                visit(e, inner)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ctx_type):
            if n.id in TRACKED and n.id not in bound:
                out.add(n.id)
        for c in ast.iter_child_nodes(n):
            visit(c, bound)

    if node is not None:
        visit(node, frozenset())
    return out


def build_units(func):
    """Map each source line to a unit: (start, uses, defs, kind, body_range)."""
    units = {}

    def add(start, end, uses, defs, kind="simple", body=None):
        unit = (start, frozenset(uses), frozenset(defs), kind, body)
        for ln in range(start, end + 1):
            units[ln] = unit

    def walk(stmts):
        for s in stmts:
            if isinstance(s, ast.While):
                add(s.lineno, s.test.end_lineno, names_in(s.test, ast.Load), set(), "while")
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.If):
                add(s.lineno, s.test.end_lineno, names_in(s.test, ast.Load), set(), "if")
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.For):
                body = (s.body[0].lineno, s.body[-1].end_lineno)
                uses = names_in(s.iter, ast.Load) | names_in(s.target, ast.Load)
                add(s.lineno, s.iter.end_lineno, uses, names_in(s.target, ast.Store), "for", body)
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, (ast.With, ast.Try, ast.FunctionDef, ast.ClassDef)):
                fail(f"unsupported statement at line {s.lineno}")
            else:
                add(s.lineno, s.end_lineno, names_in(s, ast.Load), names_in(s, ast.Store))

    walk(func.body)
    return units


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.exists():
        fail(f"trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    repo = Path.cwd()
    source = (repo / REL_FILE).read_text(encoding="utf-8")
    func = find_target(ast.parse(source))
    def_line = func.lineno
    units = build_units(func)
    params = {a.arg for a in func.args.args} & set(TRACKED)

    # Split events into invocations.
    invocations = []
    current = None
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(REL_FILE) or not m.group("func").endswith(FUNC_SUFFIX):
            continue
        ev, ln = m.group("event"), int(m.group("line"))
        if ev == "call":
            if current is not None:
                fail("nested/unterminated invocation in trace")
            current = []
        elif ev == "line":
            if current is None:
                fail(f"line event outside invocation at {ln}")
            current.append(ln)
        elif ev in ("return", "exception"):
            if ev == "return":
                if current is None:
                    fail("return without call")
                invocations.append(current)
                current = None
    if current is not None:
        fail("trace ended inside an invocation")
    if not invocations:
        fail("no addBlossom invocations found in trace")

    pairs = set()
    for lines in invocations:
        # Collapse consecutive line events of the same statement unit.
        seq = []
        for ln in lines:
            if ln not in units:
                fail(f"executed line {ln} not mapped to a statement")
            u = units[ln]
            if seq and seq[-1] is u:
                continue
            seq.append(u)
        reaching = {p: def_line for p in params}
        for idx, u in enumerate(seq):
            start, uses, defs, kind, body = u
            for var in uses:
                if var in reaching:
                    pairs.add((var, reaching[var], start))
            if kind == "for":
                nxt = seq[idx + 1] if idx + 1 < len(seq) else None
                if nxt is None or not (body[0] <= nxt[0] <= body[1]):
                    continue  # exhausting check: no binding
            for var in defs:
                reaching[var] = start

    if not pairs:
        fail("no def-use pairs derived")
    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v} for v, d, u in sorted(pairs)
        ]
    }
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]
        },
        "oracle_answer": answer,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} pairs={len(pairs)}")


if __name__ == "__main__":
    main()
