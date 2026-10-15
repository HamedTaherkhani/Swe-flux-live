#!/usr/bin/env python
"""Harvest observed def-use pairs (with counts) for EnvironBuilder.get_environ."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/werkzeug/test.py"
TARGET_CLASS = "EnvironBuilder"
TARGET_FUNC = "get_environ"
FUNC_SUFFIX = f".{TARGET_CLASS}.{TARGET_FUNC}"
TEST_REL = "werkzeug_qa/test_get_environ_m4_dataflow/files/testcase.py"
TEST_CLASS = "EnvironBuilderFlowTest"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def names(node, ctx):
    """Names with the given ctx inside ``node``, not descending into nested defs."""
    out = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Name) and isinstance(n.ctx, ctx):
            out.add(n.id)
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            stack.append(child)
    return out


class Unit:
    def __init__(self, kind, start, end, uses, defs, body_range=None):
        self.kind = kind  # "simple" | "test" | "for"
        self.start = start
        self.end = end
        self.uses = uses
        self.defs = defs
        self.body_range = body_range  # (first, last) line of for body


def build_units(func):
    units = []

    def walk(stmts):
        for s in stmts:
            if isinstance(s, ast.If):
                units.append(Unit("test", s.lineno, s.test.end_lineno, names(s.test, ast.Load), set()))
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.For):
                body_last = max(b.end_lineno for b in s.body)
                units.append(
                    Unit(
                        "for", s.lineno, s.iter.end_lineno,
                        names(s.iter, ast.Load), names(s.target, ast.Store),
                        (s.body[0].lineno, body_last),
                    )
                )
                if s.orelse:
                    fail("for-else not supported")
                walk(s.body)
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                header_end = s.body[0].lineno - 1
                uses = set()
                for d in s.decorator_list:
                    uses |= names(d, ast.Load)
                for a in s.args.defaults + s.args.kw_defaults:
                    if a is not None:
                        uses |= names(a, ast.Load)
                units.append(Unit("simple", s.lineno, header_end, uses, {s.name}))
            elif isinstance(s, (ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith)):
                fail(f"unsupported compound statement at line {s.lineno}")
            else:
                if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant):
                    continue  # docstring, not executed
                units.append(Unit("simple", s.lineno, s.end_lineno, names(s, ast.Load), names(s, ast.Store)))

    walk(func.body)
    return units


def load_target(root):
    src = (root / TARGET_REL).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == TARGET_FUNC:
                    return item
    fail("target function not found in source")


def tracked_variables(func):
    a = func.args
    params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    if a.vararg:
        params.append(a.vararg.arg)
    if a.kwarg:
        params.append(a.kwarg.arg)
    tracked = set(params)
    for u in build_units(func):
        tracked |= u.defs
    return params, tracked


def parse_trace(path):
    p = Path(path)
    if not p.is_file():
        fail(f"trace log missing: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log empty: {path}")
    invocations = []
    current = None
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("func").endswith(FUNC_SUFFIX):
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        ev = m.group("event")
        line = int(m.group("line"))
        if ev == "call":
            if current is not None:
                fail("nested/overlapping invocation of target detected")
            current = []
        elif ev == "line":
            if current is None:
                fail("line event outside of an invocation")
            current.append(line)
        elif ev == "return":
            if current is None:
                fail("return event outside of an invocation")
            invocations.append(current)
            current = None
    if current is not None:
        fail("unterminated invocation in trace")
    if not invocations:
        fail("zero events for target function in trace")
    return invocations


def analyze(invocations, func):
    units = build_units(func)
    params, tracked = tracked_variables(func)

    def unit_of(line):
        best = None
        for u in units:
            if u.start <= line <= u.end:
                if best is None or (u.end - u.start) < (best.end - best.start):
                    best = u
        if best is None:
            fail(f"executed line {line} not mapped to any statement")
        return best

    counts = Counter()
    total_lines = 0
    for lines in invocations:
        total_lines += len(lines)
        # Collapse consecutive line events of the same statement unit.
        execs = []
        for ln in lines:
            u = unit_of(ln)
            if execs and execs[-1] is u:
                continue
            execs.append(u)

        reaching = {p: func.lineno for p in params}

        def use(var, line):
            if var not in tracked:
                return
            if var not in reaching:
                fail(f"use of {var} at {line} without a reaching def")
            counts[(var, reaching[var], line)] += 1

        for i, u in enumerate(execs):
            prev = execs[i - 1] if i > 0 else None
            nxt = execs[i + 1] if i + 1 < len(execs) else None
            if u.kind == "for":
                lo, hi = u.body_range
                entering = prev is None or not (lo <= prev.start <= hi)
                if entering:
                    for v in sorted(u.uses):
                        use(v, u.start)
                if nxt is not None and lo <= nxt.start <= hi:
                    for v in u.defs:
                        if v in tracked:
                            reaching[v] = u.start
            else:
                for v in sorted(u.uses):
                    use(v, u.start)
                for v in u.defs:
                    if v in tracked:
                        reaching[v] = u.start
    return counts, total_lines, tracked


def build_question(func, tracked):
    var_list = ", ".join(f"`{v}`" for v in sorted(tracked))
    return (
        f"Run every test method of class `{TEST_CLASS}` in `{TEST_REL}` "
        f"(pytest ids `{TEST_REL}::{TEST_CLASS}::test_*`, all methods of the class). "
        f"During that run, the method `werkzeug.test.EnvironBuilder.get_environ` defined in "
        f"`{TARGET_REL}` (its `def` line is line {func.lineno}) is invoked a number of times, "
        "directly or indirectly (e.g. via `Client.open` -> `EnvironBuilder.get_request`, via "
        "`create_environ`, and again for every followed redirect). An invocation is one call of "
        "that method; invocations are independent (reaching definitions start fresh at each call). "
        "Compute all dynamically observed def-use pairs inside the frame of `get_environ` "
        "itself, summed over ALL invocations in ALL test methods of the class.\n\n"
        f"Tracked variables (exactly these local names of `get_environ`): {var_list}. "
        "Nothing else is tracked: attributes (`self.form`), subscripts (`result[key]`), globals, "
        "builtins, and anything inside the body of the nested function `_path_encode` "
        "(it runs in its own frame) are ignored.\n\n"
        "Definitions (defs): (a) the parameter `self` is defined at the `def` line of "
        "`get_environ` at the start of every invocation; (b) a name bound by an assignment "
        "statement (plain, annotated, or tuple-unpacking target) is defined at the line where "
        "that statement begins; (c) the `def _path_encode(...)` statement defines `_path_encode` "
        "at its `def` line; (d) the target names of a `for` statement are defined at the `for` "
        "line, once per loop iteration (an iteration = one execution of the loop body). "
        "Mutating an object (e.g. `result.update(...)`, `result[k] = v`, "
        "`combined_headers[...].append(...)`, `headers.remove(...)`) is NOT a def of the name; "
        "it is only a use of it. There are no augmented assignments or comprehensions in this "
        "method.\n\n"
        "Uses: a tracked name read (loaded) in an executed statement. The use line is the line "
        "where the statement begins (for multi-line statements, the first line of the statement, "
        "even if the name physically appears on a later line). For an `if`/`elif` the statement "
        "is just its condition, used at the `if`/`elif` line each time that condition is "
        "evaluated. For a `for` loop, names in the iterable expression are used once each time "
        "the loop is entered (not once per iteration), at the `for` line. For an assignment "
        "the right-hand side is read before the targets are bound. Within one execution of a "
        "statement, a variable that is read several times counts as ONE use (e.g. `self` read "
        "five times in one statement execution = one observation). A use inside a loop body "
        "counts once per iteration.\n\n"
        "A def-use pair (variable, def_line, use_line) is observed each time a use of the "
        "variable at use_line is reached by the most recent def of that variable at def_line "
        "within the same invocation (dynamic reaching definition along the path actually "
        "executed). `count` = the total number of such observations across all invocations "
        "in all test methods.\n\n"
        "Answer format: a JSON object with a single key `observed_def_use_pairs` whose value is "
        "a list of objects with keys `variable` (str, bare local name such as `foo`), "
        "`def_line` (int), `use_line` (int), `count` (int >= 1). Line numbers are absolute, "
        f"1-based line numbers in `{TARGET_REL}` as it exists in the repository. Include only "
        "pairs observed at least once; each (variable, def_line, use_line) triple appears "
        "exactly once (the count carries the multiplicity). Sort the list ascending by "
        "`variable` (Python default `str` ordering, i.e. by code point, so a leading `_` "
        "sorts before lowercase letters), then `def_line`, then `use_line` (both numerically)."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[3]))
    args = ap.parse_args()

    root = Path(args.root)
    if not (root / TARGET_REL).is_file():
        root = Path("/testbed")
    func = load_target(root)
    invocations = parse_trace(args.trace_log)
    counts, total_lines, tracked = analyze(invocations, func)
    if not counts:
        fail("no def-use pairs computed")

    pairs = [
        {"count": c, "def_line": d, "use_line": u, "variable": v}
        for (v, d, u), c in sorted(counts.items())
    ]
    oracle = {
        "question_kind": "M4_DataFlow",
        "question": build_question(func, tracked),
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} line_events={total_lines} pairs={len(pairs)}")


if __name__ == "__main__":
    main()
