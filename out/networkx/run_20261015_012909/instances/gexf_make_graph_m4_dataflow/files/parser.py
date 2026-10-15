#!/usr/bin/env python
"""Trace -> oracle.json for gexf_make_graph_m4_dataflow (observed def-use pairs with counts)."""

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter

TARGET_REL = "networkx/readwrite/gexf.py"
TARGET_CLASS = "GEXFReader"
TARGET_FUNC = "make_graph"
TARGET_QUAL = "networkx.readwrite.gexf.GEXFReader.make_graph"
TEST_FILE = "networkx_qa/gexf_make_graph_m4_dataflow/files/testcase.py"
TEST_CLASS = "TestGEXFMakeGraph"

EVENT_RE = re.compile(r"\s(\S+):(\d+)\s(\S+)\sevent=(call|line|return|exception)\b")


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def names(node, ctx):
    out = set()
    if node is None:
        return out
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ctx):
            out.add(sub.id)
    return out


def analyze_source(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_FUNC:
                    func = item
    if func is None:
        die("target function not found in source")

    params = [a.arg for a in func.args.posonlyargs + func.args.args + func.args.kwonlyargs]
    if func.args.vararg:
        params.append(func.args.vararg.arg)
    if func.args.kwarg:
        params.append(func.args.kwarg.arg)

    tracked = set(params)
    for sub in ast.walk(func):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            tracked.add(sub.id)

    # line -> (uses, defs) for simple statements / if headers
    line_info = {}
    # header line -> (iter_uses, target_defs, body_first, body_last)
    for_info = {}

    def visit(stmts):
        for st in stmts:
            ln = st.lineno
            if isinstance(st, ast.For):
                body_first = min(s.lineno for s in st.body)
                body_last = max(s.end_lineno for s in st.body)
                for_info[ln] = (
                    names(st.iter, ast.Load) & tracked,
                    names(st.target, ast.Store) & tracked,
                    body_first,
                    body_last,
                )
                if st.orelse:
                    die("for-else not supported")
                visit(st.body)
            elif isinstance(st, ast.If):
                line_info[ln] = (names(st.test, ast.Load) & tracked, set())
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, (ast.While, ast.With, ast.Try, ast.FunctionDef)):
                die(f"unsupported compound statement at line {ln}")
            else:
                if ln != st.end_lineno:
                    die(f"multi-line statement at line {ln} not supported")
                line_info[ln] = (
                    names(st, ast.Load) & tracked,
                    names(st, ast.Store) & tracked,
                )

    visit(func.body)
    return func.lineno, params, tracked, line_info, for_info


def read_invocations(trace_path, target_abs_suffix):
    if not os.path.isfile(trace_path):
        die(f"trace log missing: {trace_path}")
    if os.path.getsize(trace_path) == 0:
        die(f"trace log empty: {trace_path}")
    invocations = []
    current = None
    with open(trace_path, encoding="utf-8") as fh:
        for raw in fh:
            m = EVENT_RE.search(raw)
            if not m:
                continue
            fname, lineno, qual, event = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            if not fname.endswith(target_abs_suffix) or qual != TARGET_QUAL:
                continue
            if event == "call":
                if current is not None:
                    die("nested/unterminated invocation in trace")
                current = []
                invocations.append(current)
            elif event == "line":
                if current is None:
                    die("line event outside invocation")
                current.append(lineno)
            elif event == "return":
                if current is None:
                    die("return event outside invocation")
                current = None
    if current is not None:
        die("trace ended inside an invocation")
    if not invocations:
        die("no events for target function in trace")
    return invocations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=TARGET_REL)
    args = ap.parse_args()

    def_line, params, tracked, line_info, for_info = analyze_source(args.source)
    invocations = read_invocations(args.trace_log, TARGET_REL)

    counts = Counter()
    total_lines = 0
    for lines in invocations:
        total_lines += len(lines)
        reaching = {p: def_line for p in params}

        def use(var, ln):
            if var not in reaching:
                die(f"use of {var} at line {ln} with no reaching def")
            counts[(var, reaching[var], ln)] += 1

        for i, ln in enumerate(lines):
            if ln in for_info:
                iter_uses, target_defs, b0, b1 = for_info[ln]
                prev = lines[i - 1] if i > 0 else None
                nxt = lines[i + 1] if i + 1 < len(lines) else None
                if prev is None or not (b0 <= prev <= b1):
                    for v in sorted(iter_uses):
                        use(v, ln)
                if nxt is not None and b0 <= nxt <= b1:
                    for v in target_defs:
                        reaching[v] = ln
                continue
            if ln not in line_info:
                die(f"executed line {ln} has no static info")
            uses, defs = line_info[ln]
            for v in sorted(uses):
                use(v, ln)
            for v in defs:
                reaching[v] = ln

    if not counts:
        die("no def-use pairs observed")

    answer = {
        "observed_def_use_pairs": [
            {"count": c, "def_line": d, "use_line": u, "variable": v}
            for (v, d, u), c in sorted(counts.items())
        ]
    }

    question = f"""\
Consider the pytest test class `{TEST_CLASS}` in `{TEST_FILE}` (pytest ids `{TEST_FILE}::{TEST_CLASS}::<method>`). Run ALL test methods of that class (every `test_*` method; the answer aggregates over all of them, so method order does not matter). During this run the method `GEXFReader.make_graph` (qualname `{TARGET_QUAL}`, defined at line {def_line} of `{TARGET_REL}`) is invoked a number of times; an invocation is one call of that function (including invocations that end by raising an exception).

Report every def-use pair observed inside `make_graph` together with how many times it was observed, as {{"observed_def_use_pairs": [{{"count": int, "def_line": int, "use_line": int, "variable": str}}, ...]}}.

Definitions:
- Tracked variables: the function's parameters (`self`, `graph_xml`, `meta_xml`) plus every plain local name bound inside `make_graph` by an assignment target (including each name of a tuple target such as `x, y = ...`) or a `for` target. Module-level/global names (e.g. `nx`) are NOT tracked. Attribute or subscript stores (e.g. `obj.attr = v`, `d[k] = v`) are NOT defs of anything; the base name they are written through (`obj`, `d`) is a USE.
- Line numbers are absolute 1-based line numbers in `{TARGET_REL}` as it exists in the repository. Every statement in `make_graph` fits on a single line.
- Defs: parameters are defined at the `def` line ({def_line}) at the start of every invocation. An assignment statement defines its target names at its line. A `for` header line defines its loop target once per loop iteration (i.e. once each time the loop body is about to be entered); when the loop is exhausted no def happens.
- Uses: a tracked name read (loaded) on a line. For an `if`/`elif` line only the condition is considered. For an assignment, the right-hand side is evaluated (uses) before the targets are bound (defs), so a statement like `x = f(x)` uses the previous def of `x`. For a `for` header, the iterable expression is evaluated exactly ONCE per execution of the whole loop (once each time control reaches the loop from above, even if the loop then runs zero iterations) — it is NOT re-counted per iteration.
- Observation: every time a line executes, each distinct tracked variable read on that line produces exactly one observation (a variable appearing twice in the same statement still counts once per execution of that statement). The pair is (variable, line of the def that reaches this use at runtime, line of the use). The reaching def is the most recent def of that variable executed earlier in the SAME invocation (parameter defs reset at each invocation; nothing carries over between invocations). A use inside a loop body therefore counts once per iteration in which that line runs. Lines not executed (untaken branches, statements after a raised exception) produce nothing.
- `count` = total number of observations of that exact (variable, def_line, use_line) triple, summed over ALL invocations in ALL test methods of the class. Pairs never observed are omitted; no entry has count 0.

Output format: `variable` is the bare variable name string (e.g. "foo"); `def_line`, `use_line`, `count` are JSON integers. Each (variable, def_line, use_line) triple appears at most once. Sort the list by `variable` (ascending, plain string comparison), then `def_line` ascending, then `use_line` ascending."""

    oracle = {
        "question_kind": "M4_DataFlow",
        "question": question,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(
        f"invocations={len(invocations)} line_events={total_lines} "
        f"pairs={len(answer['observed_def_use_pairs'])}"
    )


if __name__ == "__main__":
    main()
