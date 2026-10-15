#!/usr/bin/env python
"""Derive the M4_DataFlow oracle for optuna.visualization._rank._get_rank_plot.

The trace provides the executed line sequence of every invocation of the target frame; the
target source (parsed with ``ast``) provides, per statement, which tracked names it reads and
which it binds. Reaching definitions are replayed along each executed path and every
(variable, def_line, use_line) observation is counted.
"""
import argparse
import ast
from collections import Counter
import json
import os
import re
import sys

TARGET_REL = "optuna/visualization/_rank.py"
TARGET_QUALNAME = "optuna.visualization._rank._get_rank_plot"
FUNC_NAME = "_get_rank_plot"
TEST_FILE = "optuna_qa/rank_get_rank_plot_m4_dataflow/files/testcase.py"
TEST_CLASS = "TestRankPlotScenarios"

TRACKED = [
    "colorbar_trace",
    "colormap",
    "figure",
    "info",
    "layout",
    "log_range",
    "params",
    "scatter",
    "sub_plot_info",
    "sub_plot_infos",
    "sub_plots",
    "tick_info",
    "x_i",
    "x_param",
    "xaxis",
    "y_i",
    "y_param",
    "yaxis",
]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test class `" + TEST_CLASS + "` in the file `" + TEST_FILE + "`, run as "
    "`pytest " + TEST_FILE + "::" + TEST_CLASS + "` (i.e. ALL test methods of the class, each "
    "identified by its pytest id `" + TEST_FILE + "::" + TEST_CLASS + "::<method name>`). "
    "During this run the function `optuna.visualization._rank._get_rank_plot`, defined in the "
    "file `optuna/visualization/_rank.py`, is invoked (indirectly, through "
    "`optuna.visualization.plot_rank`). An invocation is one call of this function; consider "
    "EVERY invocation made by EVERY test method of the class, and aggregate over all of them.\n\n"
    "Tracked variables (local names of the frame of `_get_rank_plot` itself), exactly: "
    + ", ".join(f"`{v}`" for v in TRACKED)
    + ". No other names are tracked (in particular not module-level names such as `go`, "
    "`math` or `make_subplots`, and not the comprehension variable `p`).\n\n"
    "Definitions (defs): (a) the parameter `info` is defined at the line of the "
    "`def _get_rank_plot(` keyword, at the start of each invocation; (b) an assignment "
    "statement `name = ...` defines `name` at the line where that statement begins; "
    "(c) a `for a, b in iterable:` header defines BOTH loop target names at the header line "
    "each time a new iteration of that loop starts. (The function contains no augmented "
    "assignments; if it did, they would count as a use followed by a def.)\n"
    "Uses: a use of a tracked variable is a read of that name in the frame of "
    "`_get_rank_plot` (as a plain value, as the object of an attribute access, subscript or "
    "method call such as `name.attr`, `name[i]` or `name.method(...)`, as a call argument, "
    "inside an f-string, in a condition, etc.). For an `if` the use is on the line of the "
    "condition. For a `for` loop, the iterable expression on the header line is evaluated "
    "ONCE each time the loop is entered (started afresh), so the names it reads are used once "
    "per loop entry, on the header line -- NOT once per iteration. The element expression of "
    "a list comprehension runs in its own frame and its reads are not uses, but the outermost "
    "iterable of a comprehension (e.g. the `xaxis.range` part of "
    "`[math.log10(p) for p in xaxis.range]`) is evaluated in this frame, so its reads ARE "
    "uses. Within one statement all reads happen before that statement's own definitions. "
    "A statement that spans several physical lines (a multi-line call, a `return`, a "
    "parenthesized expression) is attributed entirely to the line on which the statement "
    "begins: all its uses and defs are reported on that first line.\n"
    "Observation: one execution of a statement that reads a tracked variable produces exactly "
    "ONE use event for that variable, no matter how many times the name occurs textually in "
    "that statement (e.g. `f(k + 1, g(k))` executed once is one use of `k`); a statement "
    "inside a loop body therefore produces one use event per iteration in which it executes. "
    "Each use event is reached by exactly one definition of the variable: the most recently "
    "executed definition of that variable along the actual execution path of the same "
    "invocation (definitions never reach across invocations). That use event is one "
    "observation of the pair (variable, def_line, use_line).\n\n"
    "All line numbers are absolute, 1-based line numbers in "
    "`optuna/visualization/_rank.py` as it exists in the repository.\n\n"
    "Answer as a JSON object {\"observed_def_use_pairs\": [...]} whose list contains one object "
    "per distinct observed (variable, def_line, use_line) triple, with exactly the keys "
    "`variable` (string, the bare variable name exactly as spelled in the source, e.g. "
    "`\"foo_bar\"`), `def_line` (JSON integer), `use_line` (JSON integer) and `count` (JSON "
    "integer >= 1: the total number of observations of that triple, summed over all "
    "invocations in all test methods of the class). Each triple appears exactly once (the "
    "count carries the multiplicity, so there are no duplicate rows); pairs never observed are "
    "omitted. Sort the list ascending by `variable` (Python's default `str` ordering), then by "
    "`def_line`, then by `use_line`."
)


class _Collector(ast.NodeVisitor):
    """Collect Load-context names evaluated in the enclosing frame."""

    def __init__(self):
        self.uses = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.uses.add(node.id)

    def visit_Lambda(self, node):
        for d in node.args.defaults + node.args.kw_defaults:
            if d is not None:
                self.visit(d)

    def _visit_comp(self, node):
        self.visit(node.generators[0].iter)

    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_GeneratorExp = _visit_comp
    visit_DictComp = _visit_comp

    def visit_FunctionDef(self, node):
        pass


def _uses(nodes):
    c = _Collector()
    for n in nodes:
        if n is not None:
            c.visit(n)
    return c.uses


def _store_names(target):
    out = set()
    for n in ast.walk(target):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
    return out


def build_statement_table(src_path):
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    func = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            func = node
    if func is None:
        sys.exit(f"ERROR: {FUNC_NAME} not found in {src_path}")

    line_to_stmt = {}  # physical line -> statement start line
    info = {}  # statement start line -> (uses, defs)
    loops = {}  # for-header line -> (body first line, body last line)

    def register(stmt_line, span_start, span_end, uses, defs):
        for ln in range(span_start, span_end + 1):
            line_to_stmt.setdefault(ln, stmt_line)
        info[stmt_line] = (uses, defs)

    def walk(stmts):
        for s in stmts:
            if isinstance(s, ast.If):
                register(s.lineno, s.test.lineno, s.test.end_lineno, _uses([s.test]), set())
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.For):
                if s.orelse:
                    sys.exit(f"ERROR: for-else unsupported at line {s.lineno}")
                register(
                    s.lineno, s.lineno, s.iter.end_lineno, _uses([s.iter]), _store_names(s.target)
                )
                loops[s.lineno] = (s.body[0].lineno, s.end_lineno)
                walk(s.body)
            elif isinstance(s, ast.Assign):
                defs = set()
                load_parts = [s.value]
                for t in s.targets:
                    defs |= _store_names(t)
                    load_parts.append(t)
                register(s.lineno, s.lineno, s.end_lineno, _uses(load_parts), defs)
            elif isinstance(s, (ast.Expr, ast.Return)):
                register(s.lineno, s.lineno, s.end_lineno, _uses([s]), set())
            else:
                sys.exit(f"ERROR: unsupported statement {type(s).__name__} at line {s.lineno}")

    walk(func.body)
    params = {a.arg for a in func.args.args + func.args.kwonlyargs + func.args.posonlyargs}
    return func.lineno, params, line_to_stmt, info, loops


def read_invocations(trace_log):
    invocations = []
    current = None
    n_events = 0
    with open(trace_log, encoding="utf-8") as f:
        for raw in f:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_QUALNAME or not m.group("file").endswith(TARGET_REL):
                continue
            n_events += 1
            ev = m.group("event")
            ln = int(m.group("lineno"))
            if ev == "call":
                if current is not None:
                    sys.exit("ERROR: nested/recursive invocation of target")
                current = []
            elif ev == "line":
                if current is None:
                    sys.exit("ERROR: line event outside an invocation")
                current.append(ln)
            elif ev == "return":
                if current is None:
                    sys.exit("ERROR: return event outside an invocation")
                invocations.append(current)
                current = None
    if n_events == 0 or not invocations:
        sys.exit("ERROR: no events for target function in trace")
    if current is not None:
        sys.exit("ERROR: unterminated invocation in trace")
    return invocations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        sys.exit(f"ERROR: trace log missing or empty: {args.trace_log}")

    src = os.path.join(os.getcwd(), TARGET_REL)
    if not os.path.isfile(src):
        src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", TARGET_REL))
    def_line, params, line_to_stmt, info, loops = build_statement_table(src)

    invocations = read_invocations(args.trace_log)

    tracked = set(TRACKED)
    counts = Counter()
    for lines in invocations:
        # Collapse continuation lines: consecutive events of one statement execution.
        stmts = []
        for ln in lines:
            stmt = line_to_stmt.get(ln)
            if stmt is None:
                sys.exit(f"ERROR: executed line {ln} not mapped to a statement")
            if stmts and stmts[-1] == stmt:
                continue
            stmts.append(stmt)

        reaching = {p: def_line for p in params if p in tracked}
        for idx, stmt in enumerate(stmts):
            uses, defs = info[stmt]
            if stmt in loops:
                body_lo, body_hi = loops[stmt]
                prev = stmts[idx - 1] if idx > 0 else None
                nxt = stmts[idx + 1] if idx + 1 < len(stmts) else None
                entering = prev is None or not (body_lo <= prev <= body_hi)
                starts_iteration = nxt is not None and body_lo <= nxt <= body_hi
                if not entering:
                    uses = set()
                if not starts_iteration:
                    defs = set()
            for v in uses:
                if v in tracked:
                    if v not in reaching:
                        sys.exit(f"ERROR: use of {v} at {stmt} without reaching def")
                    counts[(v, reaching[v], stmt)] += 1
            for v in defs:
                if v in tracked:
                    reaching[v] = stmt

    answer = {
        "observed_def_use_pairs": [
            {"count": c, "def_line": d, "use_line": u, "variable": v}
            for (v, d, u), c in sorted(counts.items())
        ]
    }
    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(
        f"invocations={len(invocations)} line_events={sum(map(len, invocations))} "
        f"pairs={len(counts)} observations={sum(counts.values())}"
    )


if __name__ == "__main__":
    main()
