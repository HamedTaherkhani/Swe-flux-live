#!/usr/bin/env python
"""Trace -> oracle.json for M4_DataFlow on tsp_simulated_annealing."""

import argparse
import ast
from collections import Counter
import json
import os
import re
import sys

TARGET_REL = "tutorial/20_recipes/013_wilcoxon_pruner.py"
FUNC_NAME = "tsp_simulated_annealing"
QUALNAME = "tutorial.20_recipes.013_wilcoxon_pruner.tsp_simulated_annealing"
TEST_FILE = "optuna_qa/013_wilcoxon_pruner_tsp_simulated_annealing_m4_dataflow/files/testcase.py"
TEST_CLASS = "TestWilcoxonTutorialObjective"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?:retval=.*? )?locals=(?P<locals>\{.*\})\s*$"
)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_source():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in [os.path.join(os.getcwd(), TARGET_REL)] + [
        os.path.join(here, *([".."] * k), TARGET_REL) for k in range(1, 5)
    ]:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    die("target source not found")


def names_in(node, ctx):
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ctx):
            out.add(sub.id)
    return out


def analyze(src_path):
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == FUNC_NAME)
    params = [a.arg for a in fn.args.args]
    stmts = {}  # start line -> (uses, defs, kind)
    tracked = set(params)

    def visit(body):
        for st in body:
            if isinstance(st, ast.FunctionDef):
                stmts[st.lineno] = (set(), {st.name}, "def")
                tracked.add(st.name)
            elif isinstance(st, ast.For):
                stmts[st.lineno] = (names_in(st.iter, ast.Load), names_in(st.target, ast.Store), "for")
                tracked.update(names_in(st.target, ast.Store))
                visit(st.body)
            elif isinstance(st, ast.If):
                stmts[st.lineno] = (names_in(st.test, ast.Load), set(), "if")
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, ast.AugAssign):
                tgt = st.target.id
                stmts[st.lineno] = (names_in(st.value, ast.Load) | {tgt}, {tgt}, "simple")
                tracked.add(tgt)
            else:
                stmts[st.lineno] = (names_in(st, ast.Load), names_in(st, ast.Store), "simple")
                tracked.update(names_in(st, ast.Store))

    visit(fn.body)
    tracked = set(tracked)
    stmts = {ln: (u & tracked, d & tracked, k) for ln, (u, d, k) in stmts.items()}
    return fn.lineno, params, stmts, tracked


def parse_float_repr(s):
    m = re.fullmatch(r"(?:np\.float64\()?(.*?)\)?", s)
    return float(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    def_line, params, stmts, tracked = analyze(find_source())

    # Split into invocations (frames do not interleave: no recursion/threads).
    invocations = []
    cur = None
    with open(args.trace_log, encoding="utf-8") as f:
        for raw in f:
            m = LINE_RE.match(raw.rstrip("\n"))
            if not m or not m.group("file").endswith(TARGET_REL) or m.group("func") != QUALNAME:
                continue
            ev, ln = m.group("event"), int(m.group("line"))
            loc = ast.literal_eval(m.group("locals"))
            if ev == "call":
                if cur is not None:
                    die("nested/unterminated invocation")
                cur = {"events": [], "locals": dict(loc)}
                invocations.append(cur)
            elif ev in ("line", "return", "exception"):
                if cur is None:
                    die("event outside invocation")
                cur["events"].append((ev, ln, loc))
                if ev == "return":
                    cur = None
    if not invocations:
        die("zero events for target function")
    if cur is not None:
        die("unterminated invocation")

    counts = Counter()
    total_lines = 0
    for inv in invocations:
        last_def = {p: def_line for p in params}
        state = dict(inv["locals"])
        lines = [(ln, loc) for ev, ln, loc in inv["events"] if ev == "line"]
        total_lines += len(lines)
        seen_for = set()
        for idx, (ln, loc) in enumerate(lines):
            # The locals diff attached to a line event reflects the state just
            # before that line runs.
            state.update(loc)
            if ln not in stmts:
                continue  # continuation line of a multi-line statement
            uses, defs, kind = stmts[ln]
            uses = set(uses)
            defs = set(defs)
            if kind == "for":
                if ln in seen_for:
                    uses = set()  # iterable evaluated once
                seen_for.add(ln)
                nxt = lines[idx + 1][0] if idx + 1 < len(lines) else None
                if not (nxt is not None and nxt == 116):
                    defs = set()
            if ln == 129:
                # `delta_cost <= 0.0 or ... / temp`: temp is only read when the
                # left operand is false.
                if parse_float_repr(state["delta_cost"]) <= 0.0:
                    uses.discard("temp")
            for v in sorted(uses):
                if v not in last_def:
                    die(f"use of {v} at {ln} without reaching def")
                counts[(v, last_def[v], ln)] += 1
            for v in defs:
                last_def[v] = ln

    if total_lines < 60:
        die("too few line events")

    answer = {
        "observed_def_use_pairs": [
            {"count": c, "def_line": d, "use_line": u, "variable": v}
            for (v, d, u), c in sorted(counts.items())
        ]
    }
    template = {
        "observed_def_use_pairs": [
            {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
        ]
    }
    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": template,
        "oracle_answer": answer,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(oracle, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"invocations={len(invocations)} line_events={total_lines} pairs={len(counts)}")
    print(json.dumps(answer, sort_keys=True))


QUESTION = (
    "Run the pytest test class `TestWilcoxonTutorialObjective` in "
    "`optuna_qa/013_wilcoxon_pruner_tsp_simulated_annealing_m4_dataflow/files/testcase.py` "
    "(all 12 of its test methods, e.g. pytest id "
    "`optuna_qa/013_wilcoxon_pruner_tsp_simulated_annealing_m4_dataflow/files/testcase.py::TestWilcoxonTutorialObjective::test_tiny_problems`). "
    "The tests reach the function `tutorial.20_recipes.013_wilcoxon_pruner.tsp_simulated_annealing` "
    "(file `tutorial/20_recipes/013_wilcoxon_pruner.py`, `def` on line 102) indirectly through the tutorial's `objective`. "
    "Considering EVERY invocation of that function during the whole run (invocation = one call of the function; "
    "aggregate over all test methods of the class, order of methods is irrelevant because only totals are asked), "
    "report all observed dynamic def-use pairs of its local variables, each with an observation count.\n\n"
    "Tracked variables: the parameters `vertices` and `options`, and the function's own local names "
    "`temperature`, `N`, `idxs`, `cost`, `best_idxs`, `best_cost`, `remaining_patience`, `iter`, `i`, `j`, "
    "`delta_cost`, `temp`. Globals, builtins and module names (`np`, `norm`, `math`, `min`, `max`, `range`, `len`, "
    "`tsp_greedy`, `tsp_cost`, ...) are not tracked. Only statements executed in the frame of `tsp_simulated_annealing` itself count: "
    "the body of the nested function `temperature` (lines 104-105) runs in its own frame and contributes nothing, "
    "and neither do frames of any other function.\n\n"
    "Definitions (defs): the two parameters are defined at the `def` line 102 at the start of every invocation; "
    "`def temperature` defines `temperature` at line 103; a plain assignment `name = ...` (including tuple targets "
    "such as `i, j = ...`) defines each assigned name at that statement's line; an augmented assignment "
    "(`x += y`, `x -= 1`) first USES `x` (and the right-hand-side names) and then DEFINES `x`, both at its line; "
    "the `for` header on line 115 defines `iter` each time it binds a new value (i.e. once per loop iteration; the final "
    "header evaluation that exhausts `range` defines nothing). Item/slice assignments such as `a[k] = ...` or `a[:] = b` "
    "are NOT defs of `a`; they are USES of `a` (and of every name in the index and right-hand side), because they mutate "
    "the object in place. A def kills the previous def of the same variable.\n\n"
    "Uses: a variable is used at a statement when its name is read while that statement executes. Within one execution of one "
    "statement, a variable counts as used at most once even if its name appears several times (e.g. `a[k] + a[k+1]` is one use of `a`). "
    "For the multi-line statement assigning `delta_cost` (lines 122-127), every def and use is attributed to its first line, 122. "
    "The `for` header's iterable (`range(options.max_iter)`) is evaluated only once per invocation, so line 115 uses `options` once per "
    "invocation. For an `if` statement only its condition is considered (at the `if` line). Short-circuit evaluation is respected: on line 129, "
    "`delta_cost` is always used, but `temp` is used only when `delta_cost <= 0.0` is false (i.e. when the right operand of `or` is actually evaluated). "
    "Uses are processed before defs of the same statement, so `cost += delta_cost` on line 131 pairs its read of `cost` with the def that reached it "
    "from earlier (possibly line 131 itself in an earlier iteration). Calling `temperature(...)` on line 128 uses `temperature`, `iter` and `options` "
    "(the closure's own read of `options` inside line 105 does not count).\n\n"
    "An observation of the pair (variable, def_line, use_line) is one use event of `variable` at `use_line` whose reaching def "
    "(the most recent def of that variable executed earlier in the SAME invocation, or the parameter def at line 102) is at `def_line`. "
    "A use inside the loop counts once per iteration in which it executes. `count` = total number of such observations summed over all "
    "invocations in all test methods. Line numbers are absolute, 1-based line numbers in `tutorial/20_recipes/013_wilcoxon_pruner.py` as it exists in the repository.\n\n"
    "Answer format: a JSON object `{\"observed_def_use_pairs\": [...]}` whose list contains one object per distinct observed triple with keys "
    "`variable` (str, the bare variable name such as `foo`), `def_line` (int), `use_line` (int) and `count` (int, >= 1). Each (variable, def_line, use_line) "
    "triple appears exactly once (multiplicity is carried by `count`); pairs never observed are omitted. Sort the list ascending by `variable` "
    "(plain Python string order, so uppercase names sort before lowercase), then by `def_line`, then by `use_line`."
)

if __name__ == "__main__":
    main()
