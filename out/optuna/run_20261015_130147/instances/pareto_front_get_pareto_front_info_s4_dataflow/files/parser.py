#!/usr/bin/env python
"""Derive the S4_DataFlow oracle for optuna.visualization._pareto_front._get_pareto_front_info.

The trace provides the executed line sequence of every invocation of the target frame; the
target source (parsed with ``ast``) provides, per statement, which tracked names it reads and
which it binds. Reaching definitions are then replayed along the executed path.
"""
import argparse
import ast
import json
import os
import re
import sys

TARGET_REL = "optuna/visualization/_pareto_front.py"
TARGET_QUALNAME = "optuna.visualization._pareto_front._get_pareto_front_info"
FUNC_NAME = "_get_pareto_front_info"
TEST_ID = (
    "optuna_qa/pareto_front_get_pareto_front_info_s4_dataflow/files/testcase.py::"
    "TestParetoFrontScenarios::test_many_pareto_front_plots"
)

TRACKED = [
    "study",
    "target_names",
    "include_dominated_trials",
    "constraints_func",
    "targets",
    "msg",
    "feasible_trials",
    "infeasible_trials",
    "has_constraints",
    "trial",
    "constraints",
    "best_trials",
    "non_best_trials",
    "_targets",
    "n_targets",
    "metric_names",
]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test "
    "`" + TEST_ID + "` (test class `TestParetoFrontScenarios`, its single test method "
    "`test_many_pareto_front_plots`). During this test run the function "
    "`optuna.visualization._pareto_front._get_pareto_front_info`, defined in the file "
    "`optuna/visualization/_pareto_front.py`, is invoked several times (indirectly, through "
    "`optuna.visualization.plot_pareto_front`); some invocations return normally and some "
    "raise. An invocation is one call of this function; consider ALL invocations made during "
    "the test run (including those that end by raising an exception) and report the union of "
    "the def-use pairs observed in them.\n\n"
    "Tracked variables (local names of the frame of `_get_pareto_front_info` itself), exactly: "
    + ", ".join(f"`{v}`" for v in TRACKED)
    + ". No other names are tracked.\n\n"
    "Definitions (defs): (a) every parameter of the function is defined at the line of the "
    "`def _get_pareto_front_info(` keyword, at the start of each invocation (all five "
    "parameters always count as bound there, whether passed explicitly or defaulted); "
    "(b) an assignment statement `name = ...` defines `name` at the line where that statement "
    "begins; (c) an augmented assignment `name op= expr` is BOTH a use of the reaching "
    "definition of `name` and a new definition of `name` on that line (the use happens first); "
    "(d) a `for name in iterable:` header redefines `name` at the header line each time a new "
    "iteration starts (the iterable expression on the header line counts as a use of the names "
    "it reads, on the header line, each time the header line executes).\n"
    "Uses: a use of a tracked variable is any read of that name in the frame of "
    "`_get_pareto_front_info` (as a plain value, as the object of an attribute access or "
    "method call such as `name.attr` or `name.append(...)`, as a call argument, inside an "
    "f-string, in a condition, etc.). Within one statement all reads happen before that "
    "statement's own definitions (so in `x = f(x)` the read sees the previous definition). "
    "For an `if`/`elif` the use is on the line of the condition; for a `for` loop, on the "
    "header line. A statement that spans several physical lines (a call, a `raise`, a "
    "`return` with arguments on following lines, a parenthesized expression) is attributed "
    "entirely to the line on which the statement begins: all its uses and defs are reported "
    "on that first line. Names bound or read inside lambda bodies, inside the element/condition "
    "part of comprehensions or generator expressions, and anywhere inside the bodies of the "
    "nested functions `_make_trials_with_values` and `_infer_n_targets` are NOT part of this "
    "frame: their loop/parameter names are not tracked and reads there are not uses (the "
    "outermost iterable of a comprehension/generator expression IS evaluated in this frame, "
    "so reads in it are uses on the line where the enclosing statement begins). "
    "In particular, the parameter `targets` of the nested function "
    "`_make_trials_with_values` is a different variable from the tracked `targets`.\n"
    "A def-use pair (variable, def_line, use_line) is observed when, during some invocation, the "
    "value bound by the definition of `variable` at def_line is the one read at use_line "
    "(i.e. no other definition of `variable` executed in between along the actual execution "
    "path of that invocation). Definitions never reach across invocations.\n\n"
    "All line numbers are absolute, 1-based line numbers in "
    "`optuna/visualization/_pareto_front.py` as it exists in the repository.\n\n"
    "Answer as a JSON object {\"observed_def_use_pairs\": [...]} whose list contains one object "
    "per unique observed pair, with exactly the keys `variable` (string, the bare variable "
    "name exactly as spelled in the source, e.g. `\"foo_bar\"`, including any leading "
    "underscore), `def_line` (JSON integer) and `use_line` (JSON integer). Each unique "
    "(variable, def_line, use_line) triple appears exactly once, no matter how many times or "
    "in how many invocations it was observed. Sort the list ascending by `variable` (plain "
    "string comparison of the names, i.e. Python's default `str` ordering, in which `_` sorts "
    "before lowercase letters), then by `def_line`, then by `use_line`."
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
                register(
                    s.lineno, s.lineno, s.iter.end_lineno, _uses([s.iter]), _store_names(s.target)
                )
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, ast.FunctionDef):
                register(s.lineno, s.lineno, s.lineno, set(), {s.name})
            elif isinstance(s, ast.Assign):
                defs = set()
                load_parts = [s.value]
                for t in s.targets:
                    defs |= _store_names(t)
                    load_parts.append(t)
                register(s.lineno, s.lineno, s.end_lineno, _uses(load_parts), defs)
            elif isinstance(s, ast.AugAssign):
                defs = _store_names(s.target)
                register(s.lineno, s.lineno, s.end_lineno, _uses([s.value]) | defs, defs)
            elif isinstance(s, ast.AnnAssign):
                defs = _store_names(s.target)
                register(s.lineno, s.lineno, s.end_lineno, _uses([s.value]), defs)
            elif isinstance(s, (ast.Expr, ast.Return, ast.Raise, ast.Continue, ast.Break, ast.Pass)):
                register(s.lineno, s.lineno, s.end_lineno, _uses([s]), set())
            else:
                sys.exit(f"ERROR: unsupported statement {type(s).__name__} at line {s.lineno}")

    walk(func.body)
    params = {a.arg for a in func.args.args + func.args.kwonlyargs + func.args.posonlyargs}
    return func.lineno, params, line_to_stmt, info


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
    def_line, params, line_to_stmt, info = build_statement_table(src)

    # Split trace into invocations (sequence of executed line numbers).
    invocations = []
    current = None
    n_events = 0
    with open(args.trace_log, encoding="utf-8") as f:
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

    tracked = set(TRACKED)
    pairs = set()
    for lines in invocations:
        reaching = {p: def_line for p in params if p in tracked}
        prev_stmt = None
        for ln in lines:
            stmt = line_to_stmt.get(ln)
            if stmt is None:
                sys.exit(f"ERROR: executed line {ln} not mapped to a statement")
            if stmt == prev_stmt:
                continue  # continuation line of the same statement execution
            prev_stmt = stmt
            uses, defs = info[stmt]
            for v in uses:
                if v in tracked:
                    if v not in reaching:
                        sys.exit(f"ERROR: use of {v} at {stmt} without reaching def")
                    pairs.add((v, reaching[v], stmt))
            for v in defs:
                if v in tracked:
                    reaching[v] = stmt

    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v} for (v, d, u) in sorted(pairs)
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
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"invocations={len(invocations)} line_events={sum(map(len, invocations))} "
          f"pairs={len(pairs)}")


if __name__ == "__main__":
    main()
