#!/usr/bin/env python
"""Derive observed def-use pairs of selected locals of parse_pajek from the trace."""

import argparse
import ast
import json
import os
import re
import sys

REL_FILE = "networkx/readwrite/pajek.py"
FUNC = "networkx.readwrite.pajek.parse_pajek"
FUNC_NAME = "parse_pajek"
TRACKED = [
    "G",
    "edge_data",
    "extra_attr",
    "l",
    "label",
    "lines",
    "nodelabels",
    "splitline",
    "u",
    "v",
    "w",
]
TEST_ID = (
    "networkx_qa/pajek_parse_pajek_s4_dataflow/files/testcase.py"
    "::TestPajekRoundTrip::test_read_mixed_sections"
)

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test "
    f"`{TEST_ID}` (test file `networkx_qa/pajek_parse_pajek_s4_dataflow/files/testcase.py`, "
    "class `TestPajekRoundTrip`, single test method `test_read_mixed_sections`), run from the repository root "
    "with the repository's Python (CPython 3.12). During this test the function `parse_pajek` defined in "
    "`networkx/readwrite/pajek.py` (fully qualified `networkx.readwrite.pajek.parse_pajek`) is reached indirectly "
    "through `nx.read_pajek`. Consider every invocation of `parse_pajek` during the test (one invocation = one call "
    "of the function; aggregate over all of them) and report the dynamic def-use pairs observed in the function's "
    "own frame for exactly these tracked local variable names: "
    + ", ".join(f"`{v}`" for v in TRACKED)
    + ". No other names are tracked.\n\n"
    "Statement-level model. Work at the granularity of executed statements of `parse_pajek` itself. Every def and "
    "every use is attributed to the line where the statement BEGINS (absolute 1-based line number in "
    "`networkx/readwrite/pajek.py` as it exists in the repository); for a statement spanning several physical "
    "lines, use its first line even if the interpreter reports a later line while evaluating it. For compound "
    "statements only the header counts: an `if`/`elif`/`while` header is attributed to the line of the "
    "`if`/`elif`/`while` keyword and uses the names read in its condition (a header executes whenever its "
    "condition is evaluated); a `for` header is attributed to the line of the `for` keyword; `try:`, `except ...:`, "
    "`pass`, `break` and `continue` neither define nor use tracked names. Decorator lines never appear.\n\n"
    "Def: a tracked name is defined (a) at the `def parse_pajek(` line (the `def` keyword line, not the decorator "
    "line) for the parameter `lines` when the function is entered, (b) at a statement that binds it as a plain "
    "assignment target (including tuple-unpacking targets), and (c) at a `for` header each time the loop yields "
    "an item and binds the loop target (the final evaluation of the header that finds the iterator exhausted "
    "binds nothing). A statement that raises an exception while executing (whether or not it is caught later) "
    "defines nothing. Augmented assignment (`x += 1`) would count as a use of the current def of `x` followed by "
    "a new def of `x` on that line (none of the tracked names is augmented-assigned here). Assigning through a "
    "subscript or attribute (`d[k] = v`, `obj.a[k] = v`) and calling a mutating method (`d.update(...)`) are "
    "uses of `d`/`obj`, NOT defs. Names bound only inside a comprehension (comprehension loop variables) are "
    "comprehension-local and are never tracked; none of the tracked names is a comprehension variable.\n\n"
    "Use: a tracked name is used at a statement each time that statement executes and its source text reads "
    "the name (a load, anywhere in the statement or header, including inside a comprehension's expressions and "
    "including the iterable expression of a `for` header, which counts as read on every evaluation of the "
    "header). A statement that raises still counts as using every tracked name it reads (in this run all such "
    "reads happen before the raise). Within one statement, uses happen before defs, so e.g. `y = f(y)` uses "
    "the previous def of `y` and then creates a new one.\n\n"
    "Pair: `{variable, def_line, use_line}` is observed when, at some execution of the use statement, the "
    "most recent def of `variable` in the same invocation's frame happened at `def_line` (i.e. the value "
    "defined there is read before being redefined). A def that is never read before being redefined or before "
    "the function returns produces no pair. Pairs are deduplicated across all executions and invocations.\n\n"
    "Answer format: a JSON object `{\"observed_def_use_pairs\": [...]}` whose list contains one object per unique "
    "pair with exactly the keys `variable` (string, the bare local name exactly as listed above), `def_line` "
    "(integer) and `use_line` (integer). Sort the list by `variable` (ascending, plain code-point string "
    "comparison, so uppercase names sort before lowercase), then `def_line` ascending, then `use_line` ascending."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


class StmtInfo:
    def __init__(self, node, uses, defs, kind):
        self.node = node
        self.line = node.lineno
        self.uses = uses
        self.defs = defs
        self.kind = kind  # "simple", "header", "for", "none"


def names_in(nodes, ctx):
    out = set()
    for n in nodes:
        if n is None:
            continue
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ctx):
                out.add(sub.id)
    return out


def comp_bound(nodes):
    out = set()
    for n in nodes:
        if n is None:
            continue
        for sub in ast.walk(n):
            if isinstance(sub, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                for gen in sub.generators:
                    out |= names_in([gen.target], ast.Store)
    return out


def analyze(source_path):
    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            func = node
    if func is None:
        fail("target function not found in source")
    tracked = set(TRACKED)
    spans = []  # (start, end, depth, StmtInfo)

    def visit(stmts, depth):
        for st in stmts:
            if isinstance(st, (ast.If, ast.While)):
                parts = [st.test]
                cb = comp_bound(parts)
                info = StmtInfo(st, (names_in(parts, ast.Load) - cb) & tracked, set(), "header")
                spans.append((st.lineno, st.test.end_lineno, depth, info))
                visit(st.body, depth + 1)
                visit(st.orelse, depth + 1)
            elif isinstance(st, ast.For):
                parts = [st.iter]
                cb = comp_bound(parts)
                uses = (names_in(parts, ast.Load) - cb) & tracked
                defs = names_in([st.target], ast.Store) & tracked
                info = StmtInfo(st, uses, defs, "for")
                info.body_line = st.body[0].lineno
                spans.append((st.lineno, st.iter.end_lineno, depth, info))
                visit(st.body, depth + 1)
                visit(st.orelse, depth + 1)
            elif isinstance(st, ast.Try):
                spans.append((st.lineno, st.lineno, depth, StmtInfo(st, set(), set(), "none")))
                visit(st.body, depth + 1)
                for h in st.handlers:
                    spans.append((h.lineno, h.lineno, depth, StmtInfo(h, set(), set(), "none")))
                    visit(h.body, depth + 1)
                visit(st.orelse, depth + 1)
                visit(st.finalbody, depth + 1)
            elif isinstance(st, (ast.With, ast.FunctionDef, ast.ClassDef, ast.AsyncFor, ast.Match)):
                fail(f"unsupported statement at line {st.lineno}")
            else:
                cb = comp_bound([st])
                uses = names_in([st], ast.Load) - cb
                defs = names_in([st], ast.Store) - cb
                if isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name):
                    uses.add(st.target.id)
                info = StmtInfo(st, uses & tracked, defs & tracked, "simple")
                spans.append((st.lineno, st.end_lineno, depth, info))

    visit(func.body, 0)
    return func, spans


def stmt_for_line(spans, line):
    best = None
    for start, end, depth, info in spans:
        if start <= line <= end and (best is None or depth > best[0]):
            best = (depth, info)
    if best is None:
        fail(f"line {line} does not map to a statement of the target")
    return best[1]


def parse_trace(path):
    if not os.path.exists(path):
        fail(f"trace log not found: {path}")
    with open(path, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        fail("trace log is empty")
    invocations = []
    current = None
    for text in raw:
        m = LINE_RE.match(text)
        if not m:
            continue
        if m.group("func") != FUNC or not m.group("file").endswith(REL_FILE):
            continue
        ev = m.group("event")
        line = int(m.group("line"))
        if ev == "call":
            if current is not None:
                fail("nested invocation of target (unexpected)")
            current = []
            invocations.append(current)
        elif ev in ("line", "exception"):
            if current is None:
                fail(f"{ev} event outside an invocation")
            current.append((ev, line))
        elif ev == "return":
            if current is None:
                fail("return outside an invocation")
            current = None
    if not invocations or not any(invocations):
        fail("zero events for target function in trace")
    return invocations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=os.path.join(os.getcwd(), REL_FILE))
    args = ap.parse_args()

    func, spans = analyze(args.source)
    params = {a.arg for a in func.args.args} & set(TRACKED)
    invocations = parse_trace(args.trace_log)

    pairs = set()
    for events in invocations:
        # group consecutive events into statement executions
        execs = []  # [info, raised]
        for ev, line in events:
            info = stmt_for_line(spans, line)
            if ev == "exception":
                if not execs or execs[-1][0] is not info:
                    fail(f"exception at line {line} not inside current statement")
                execs[-1][1] = True
                continue
            if execs and execs[-1][0] is info and not execs[-1][1]:
                continue
            execs.append([info, False])
        reaching = {p: func.lineno for p in params}
        for idx, (info, raised) in enumerate(execs):
            for var in sorted(info.uses):
                if var in reaching:
                    pairs.add((var, reaching[var], info.line))
            if raised:
                continue
            if info.kind == "for":
                nxt = execs[idx + 1][0] if idx + 1 < len(execs) else None
                if nxt is None or nxt.line != info.body_line:
                    continue
            for var in info.defs:
                reaching[var] = info.line

    if not pairs:
        fail("no def-use pairs observed")
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
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"invocations={len(invocations)} pairs={len(pairs)}")
    for v, d, u in sorted(pairs):
        print(f"  {v} {d} -> {u}")


if __name__ == "__main__":
    main()
