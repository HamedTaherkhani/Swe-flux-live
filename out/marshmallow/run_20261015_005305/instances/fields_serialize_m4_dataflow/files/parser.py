#!/usr/bin/env python
"""Derive the M4_DataFlow oracle (observed def-use pairs with counts) for
marshmallow.fields.Mapping._serialize from a line-level trace log."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/marshmallow/fields.py"
TARGET_QUAL = "marshmallow.fields.Mapping._serialize"
TEST_REL = "marshmallow_qa/fields_serialize_m4_dataflow/files/testcase.py"
TEST_CLASS = "MappingDumpScenarios"

LINE_RE = re.compile(r"\s(\S+):(\d+) (\S+) event=(\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_function(src_path):
    tree = ast.parse(Path(src_path).read_text(encoding="utf-8"))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "Mapping":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "_serialize":
                    return fn
    fail("Mapping._serialize not found in source")


def names_used(node, tracked):
    """Outer-scope tracked names read by an expression; comprehension
    target names are local to the comprehension and are not outer uses."""
    used = set()

    def visit(n, shadowed):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            inner = set(shadowed)
            for i, gen in enumerate(n.generators):
                visit(gen.iter, shadowed if i == 0 else inner)
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        inner.add(t.id)
                for cond in gen.ifs:
                    visit(cond, inner)
            if isinstance(n, ast.DictComp):
                visit(n.key, inner)
                visit(n.value, inner)
            else:
                visit(n.elt, inner)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id in tracked and n.id not in shadowed:
                used.add(n.id)
        for c in ast.iter_child_nodes(n):
            visit(c, shadowed)

    visit(node, frozenset())
    return used


def names_stored(node, tracked):
    return {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in tracked
    }


def build_model(fn):
    params = [a.arg for a in fn.args.args]
    if fn.args.vararg:
        params.append(fn.args.vararg.arg)
    params += [a.arg for a in fn.args.kwonlyargs]
    if fn.args.kwarg:
        params.append(fn.args.kwarg.arg)
    tracked = set(params)
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            tracked.add(n.id)
    # Remove comprehension-only targets that are never bound in the function
    # scope itself (none here: `k` is also a for-loop target).

    stmts = {}  # first line -> dict(kind, span, uses, defs, ...)
    loops = {}

    def add_stmts(body):
        for s in body:
            if isinstance(s, ast.If):
                stmts[s.lineno] = dict(
                    kind="simple", span=range(s.test.lineno, s.test.end_lineno + 1),
                    uses=names_used(s.test, tracked), defs=set())
                add_stmts(s.body)
                add_stmts(s.orelse)
            elif isinstance(s, ast.For):
                body_lines = set()
                for b in s.body:
                    body_lines.update(range(b.lineno, b.end_lineno + 1))
                stmts[s.lineno] = dict(
                    kind="for", span=range(s.lineno, s.iter.end_lineno + 1),
                    uses=names_used(s.iter, tracked),
                    defs=names_stored(s.target, tracked), body=body_lines)
                add_stmts(s.body)
            elif isinstance(s, (ast.Assign, ast.Return, ast.Expr)):
                uses = set()
                defs = set()
                if isinstance(s, ast.Assign):
                    uses |= names_used(s.value, tracked)
                    for t in s.targets:
                        if isinstance(t, ast.Name):
                            defs.add(t.id)
                        else:
                            uses |= names_used(t, tracked)
                elif s.value is not None:
                    uses |= names_used(s.value, tracked)
                stmts[s.lineno] = dict(
                    kind="simple", span=range(s.lineno, s.end_lineno + 1),
                    uses=uses, defs=defs)
            else:
                fail(f"unsupported statement at line {s.lineno}")

    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    add_stmts(body)
    line_to_stmt = {}
    for first, info in stmts.items():
        for ln in info["span"]:
            line_to_stmt[ln] = first
    return fn.lineno, params, tracked, stmts, line_to_stmt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    root = Path(__file__).resolve().parents[3]
    src = root / TARGET_REL
    if not src.is_file():
        src = Path("/testbed") / TARGET_REL
    def_line, params, tracked, stmts, line_to_stmt = build_model(find_function(src))

    # Collect target-frame events; each invocation is a frame on a stack.
    frames = []  # finished invocations: list of event lists
    stack = []
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.search(raw)
        if not m:
            continue
        path, lineno, qual, event = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        if not path.replace("\\", "/").endswith(TARGET_REL) or qual != TARGET_QUAL:
            continue
        if event == "call":
            stack.append([])
        elif event == "line":
            if not stack:
                fail("line event outside an invocation")
            stack[-1].append(lineno)
        elif event == "return":
            if not stack:
                fail("unbalanced return event")
            frames.append(stack.pop())
        elif event == "exception":
            fail(f"unexpected exception event at line {lineno}")
    if stack:
        fail("trace ended inside an invocation")
    if not frames:
        fail("zero invocations of the target found in trace")

    counts = Counter()
    total_lines = 0
    for lines in frames:
        total_lines += len(lines)
        reaching = {p: def_line for p in params}
        # Collapse line events into statement executions.
        execs = []  # (stmt_first_line, raw_line)
        prev = None
        for ln in lines:
            st = line_to_stmt.get(ln)
            if st is None:
                fail(f"line {ln} not mapped to a statement")
            info = stmts[st]
            if info["kind"] == "simple" and prev == st:
                continue
            execs.append(st)
            prev = st
        for i, st in enumerate(execs):
            info = stmts[st]
            if info["kind"] == "for":
                prev_st = execs[i - 1] if i > 0 else None
                nxt = execs[i + 1] if i + 1 < len(execs) else None
                entering = prev_st is None or prev_st not in info["body"]
                iterating = nxt is not None and nxt in info["body"]
                if entering:
                    for var in info["uses"]:
                        counts[(var, reaching[var], st)] += 1
                if iterating:
                    for var in info["defs"]:
                        reaching[var] = st
            else:
                for var in info["uses"]:
                    if var not in reaching:
                        fail(f"use of undefined {var} at {st}")
                    counts[(var, reaching[var], st)] += 1
                for var in info["defs"]:
                    reaching[var] = st

    answer = [
        {"count": c, "def_line": d, "use_line": u, "variable": v}
        for (v, d, u), c in sorted(counts.items())
    ]
    if not answer:
        fail("no def-use pairs observed")

    question = build_question(def_line)
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
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(frames)} line_events={total_lines} pairs={len(answer)}")


def build_question(def_line):
    return f"""Consider the test class `{TEST_CLASS}` in `{TEST_REL}`. Run ALL test methods of that class (pytest ids of the form `{TEST_REL}::{TEST_CLASS}::test_<name>`) as one pytest run. The answer is a TOTAL aggregated over every test method in the class (summing makes it independent of test order).

Target function: `marshmallow.fields.Mapping._serialize`, defined in `{TARGET_REL}` (the `def` line is line {def_line}). Line numbers are absolute, 1-based line numbers in that file as it exists in the repository. The tests never call the target directly; it is reached through `Schema.dump` -> `Field.serialize` and through container fields (`fields.List`, `fields.Tuple`, `fields.Nested`, and `Mapping._serialize` itself via `self.value_field._serialize(...)`). An invocation = one call of `Mapping._serialize` (on any `fields.Dict` instance) during the run, including recursive calls; every invocation is analysed independently with its own variables (a recursive call does not affect the caller's def-use state).

Tracked variables: the function's parameters `self`, `value`, `attr`, `obj`, `kwargs` and its local variables `keys`, `result`, `k`, `v`. Names that are not these (e.g. `None`, `dict`) are not tracked. The comprehension variable `k` inside the dict comprehensions on the `keys = ...` statements is local to the comprehension and is NOT the tracked `k`; a comprehension's references to `k` are neither uses nor defs.

Definitions (defs):
- every parameter is defined at the `def` line once at the start of each invocation;
- an assignment statement `name = ...` defines `name` at the statement's first line (the multi-line `keys = {{ ... }}` statement is identified by the line on which it begins);
- a `for` header defines its target variables (`k` and `v`) once per iteration, i.e. each time the iterator yields an item, at the header line.
- A subscript assignment `result[...] = ...` is NOT a def of `result`; it is a use of `result` (and of every tracked name in the subscript and right-hand side).

Uses: a statement uses each tracked variable whose name it reads (attribute access like `self.key_field` is a use of `self`; `**kwargs` is a use of `kwargs`). A variable read several times in one statement counts as ONE use per statement execution. For an `if` statement, the use belongs to the `if` line and its condition is considered as a whole (short-circuiting does not remove a use of a variable that appears in it). A `return X` statement uses the tracked names in `X`. A statement that contains a comprehension (`keys = {{...}}`) is executed once and uses each outer tracked name that appears anywhere in it exactly once per execution of the statement, regardless of how many elements the comprehension processes. For a `for` header, the iterable expression (`value.items()`) is evaluated once each time the loop is entered, so it records exactly one use of `value` per loop entry (including entries where the mapping is empty), NOT one per iteration. Within a statement, uses are evaluated before the statement's defs.

Observation: each time a statement executes and uses a variable, record one observation of the pair (variable, def_line, use_line), where use_line is the line on which the using statement begins and def_line is the line of the most recent def of that variable in the same invocation (the def that reaches that use on the executed path). A use inside a loop body therefore counts once per iteration. `count` = the total number of observations of that exact (variable, def_line, use_line) triple summed over all invocations in all test methods of the class.

Answer format: a JSON object with a single key `observed_def_use_pairs` whose value is a list of objects with exactly the keys `variable` (str, the bare variable name such as "self"), `def_line` (int), `use_line` (int) and `count` (int, >= 1). Include only triples observed at least once; each triple appears exactly once (multiplicity lives in `count`). Sort the list ascending by `variable` (plain string order), then by `def_line`, then by `use_line`."""


if __name__ == "__main__":
    main()
