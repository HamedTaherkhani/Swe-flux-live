#!/usr/bin/env python
"""Trace -> oracle.json for probability_distributions_sample_m4_dataflow (M4_DataFlow)."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
import os
import re
import sys


TARGET_REL = "optuna/samplers/_tpe/probability_distributions.py"
TARGET_QUALNAME = "optuna.samplers._tpe.probability_distributions._MixtureOfProductDistribution.sample"
CLASS_NAME = "_MixtureOfProductDistribution"
FUNC_NAME = "sample"
TEST_FILE = "optuna_qa/probability_distributions_sample_m4_dataflow/files/testcase.py"
TEST_CLASS = "TestMixtureSampleDataFlow"

EVENT_RE = re.compile(r"(\S+\.py):(\d+) (\S+) event=(\w+)")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- static model
def find_function(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == FUNC_NAME:
                    return item
    fail("target function not found in source")
    raise AssertionError


def comp_bound(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for gen in node.generators:  # type: ignore[attr-defined]
        for n in ast.walk(gen.target):
            if isinstance(n, ast.Name):
                names.add(n.id)
    return names


def load_names(node: ast.AST, shadow: frozenset = frozenset()) -> set[str]:
    """Names read in an expression; comprehension-bound names are excluded."""
    out: set[str] = set()
    if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
        inner = shadow | comp_bound(node)
        for child in ast.iter_child_nodes(node):
            out |= load_names(child, inner)
        return out
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id not in shadow:
            out.add(node.id)
        return out
    for child in ast.iter_child_nodes(node):
        out |= load_names(child, shadow)
    return out


def target_effects(t: ast.AST) -> tuple[set[str], set[str]]:
    """(uses, defs) of an assignment target."""
    uses: set[str] = set()
    defs: set[str] = set()
    if isinstance(t, ast.Name):
        defs.add(t.id)
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            u, d = target_effects(e)
            uses |= u
            defs |= d
    elif isinstance(t, ast.Subscript):
        uses |= load_names(t.slice)
        if isinstance(t.value, ast.Name):
            uses.add(t.value.id)
            defs.add(t.value.id)  # in-place mutation counts as a def
        else:
            uses |= load_names(t.value)
    else:
        uses |= load_names(t)
    return uses, defs


class StmtInfo:
    def __init__(self, key: int, kind: str, uses: set[str], defs: set[str],
                 entry_uses: set[str] | None = None, body_lines: set[int] | None = None):
        self.key = key
        self.kind = kind  # "simple", "if", "for"
        self.uses = uses
        self.defs = defs
        self.entry_uses = entry_uses or set()
        self.body_lines = body_lines or set()


def build_model(func: ast.FunctionDef):
    params = [a.arg for a in func.args.args]
    line_to_key: dict[int, int] = {}
    infos: dict[int, StmtInfo] = {}

    def body_line_set(stmts) -> set[int]:
        s: set[int] = set()
        for st in stmts:
            s |= set(range(st.lineno, st.end_lineno + 1))
        return s

    def visit(stmts):
        for st in stmts:
            if isinstance(st, ast.If):
                key = st.lineno
                for ln in range(st.test.lineno, st.test.end_lineno + 1):
                    line_to_key[ln] = key
                infos[key] = StmtInfo(key, "if", load_names(st.test), set())
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, ast.For):
                key = st.lineno
                for ln in range(st.lineno, st.iter.end_lineno + 1):
                    line_to_key[ln] = key
                _, tdefs = target_effects(st.target)
                infos[key] = StmtInfo(key, "for", set(), tdefs,
                                      entry_uses=load_names(st.iter),
                                      body_lines=body_line_set(st.body))
                visit(st.body)
            else:
                key = st.lineno
                for ln in range(st.lineno, st.end_lineno + 1):
                    line_to_key[ln] = key
                uses: set[str] = set()
                defs: set[str] = set()
                if isinstance(st, ast.Assign):
                    uses |= load_names(st.value)
                    for t in st.targets:
                        u, d = target_effects(t)
                        uses |= u
                        defs |= d
                elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) \
                        and isinstance(st.value.func, ast.Attribute) \
                        and isinstance(st.value.func.value, ast.Name):
                    uses |= load_names(st.value)
                    defs.add(st.value.func.value.id)  # method call mutates receiver
                else:
                    uses |= load_names(st)
                infos[key] = StmtInfo(key, "simple", uses, defs)

    visit(func.body)

    local_vars = set(params)
    for info in infos.values():
        local_vars |= info.defs
    for info in infos.values():
        info.uses &= local_vars
        info.entry_uses &= local_vars
    return params, line_to_key, infos


# ---------------------------------------------------------------- trace
def read_invocations(path: str, target_abs_suffix: str) -> list[list[int]]:
    if not os.path.isfile(path):
        fail(f"trace log missing: {path}")
    if os.path.getsize(path) == 0:
        fail(f"trace log empty: {path}")
    invocations: list[list[int]] = []
    current: list[int] | None = None
    n_events = 0
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            m = EVENT_RE.search(raw)
            if not m:
                continue
            fpath, lineno, func, event = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            if not fpath.replace("\\", "/").endswith(target_abs_suffix) or func != TARGET_QUALNAME:
                continue
            n_events += 1
            if event == "call":
                if current is not None:
                    fail("nested/unterminated invocation in trace")
                current = []
            elif event == "line":
                if current is None:
                    fail("line event outside an invocation")
                current.append(lineno)
            elif event == "return":
                if current is None:
                    fail("return event outside an invocation")
                invocations.append(current)
                current = None
            elif event == "exception":
                fail("unexpected exception event in target function")
    if n_events == 0:
        fail("trace contains zero events for the target function")
    if current is not None:
        fail("trace ends inside an invocation")
    if not invocations:
        fail("no complete invocations of the target in the trace")
    return invocations


def analyze(invocations, params, func_line, line_to_key, infos) -> Counter:
    counts: Counter = Counter()
    for lines in invocations:
        execs: list[int] = []
        for ln in lines:
            if ln not in line_to_key:
                fail(f"line {ln} not mapped to any statement")
            key = line_to_key[ln]
            if execs and execs[-1] == key:
                continue  # same statement continuing (multi-line expression)
            execs.append(key)
        reaching = {p: func_line for p in params}

        def use(var: str, at: int) -> None:
            if var not in reaching:
                fail(f"use of {var} at {at} with no reaching def")
            counts[(var, reaching[var], at)] += 1

        for idx, key in enumerate(execs):
            info = infos[key]
            if info.kind == "for":
                prev = execs[idx - 1] if idx > 0 else None
                nxt = execs[idx + 1] if idx + 1 < len(execs) else None
                if prev is None or prev not in info.body_lines:
                    for v in sorted(info.entry_uses):
                        use(v, key)
                if nxt is not None and nxt in info.body_lines:
                    for v in sorted(info.defs):
                        reaching[v] = key
                continue
            for v in sorted(info.uses):
                use(v, key)
            for v in sorted(info.defs):
                reaching[v] = key
    return counts


QUESTION = f"""\
Consider the test class `{TEST_CLASS}` in `{TEST_FILE}` (pytest id `{TEST_FILE}::{TEST_CLASS}`). Run ALL of its test methods (every `test_...` method of the class; the answer aggregates over all of them). Focus on the method `{TARGET_QUALNAME}` (i.e. `_MixtureOfProductDistribution.sample`) defined in `{TARGET_REL}`. An invocation is one call of this method during the run; every invocation in every test method is included.

Report every def-use pair that is actually observed at runtime inside this method, together with how many times it is observed.

Definitions:
- Tracked variables: only local names of `sample`'s own frame: the parameters `self`, `rng`, `batch_size`, plus every name bound by an assignment or `for` target in the method body. Globals/builtins/modules (`np`, `_truncnorm`, `len`, `isinstance`, `enumerate`, class names, ...) are NOT tracked. Variables bound only inside a list comprehension (e.g. the `d` in `[d.mu[...] for d in numerical_dists]`) are comprehension-local: they are neither defs nor uses, and they never touch the loop variable `d` of the `for` statement. Names of the enclosing frame read inside a comprehension (e.g. `active_indices`, `numerical_dists`) ARE uses by the enclosing statement.
- Parameters are defined at the `def` line (line 143) at the start of every invocation.
- A "statement" is a simple statement (assignment, expression statement, assert, return) or the header of a compound statement (the condition of an `if`, the `for ... in ...:` header). A statement spanning several physical lines is identified by its FIRST line (e.g. the call assigned to `ret[:, numerical_inds]` is identified by line 171, the `np.clip` assignment by line 182); all its uses/defs are attributed to that line.
- Defs: (a) a plain name assignment target (including each name of a tuple-unpacking target) defines that name; (b) an assignment whose target is a subscript of a tracked name, e.g. `x[k] = v`, both USES `x` and then DEFINES `x` (an in-place mutation is treated as a new def); names in the subscript index are uses; (c) an expression statement that is a method call on a tracked name, e.g. `x.append(y)`, both USES `x` (and `y`) and then DEFINES `x`; (d) the `for` header at line 149 defines `i` and `d` once per iteration (i.e. each time it hands a new element to the loop body; the final check that exhausts the iterator defines nothing).
- Uses: every tracked name read anywhere in the statement (including inside comprehensions, call arguments, attribute bases like `self.weights`, subscript indices, `assert` and `return` expressions, and `if` conditions). The `for` header at line 149 uses `self` exactly once each time the loop is entered (once per invocation), not once per iteration. Within one statement execution, a name read several times counts as ONE use; all uses of a statement happen before its defs (so a statement like `x[k] = f(x)` reads the previous def of `x` and then defines `x` at its own line).
- The def that reaches a use is the most recent def of that variable executed earlier in the same invocation (along the actual executed path; loop-carried defs from earlier iterations count).
- An observation is one use event: one execution of a statement that uses the variable, paired with the def that reaches it at that moment. A use inside a loop body is therefore observed once per iteration in which that statement executes.

Answer format: a JSON object `{{"observed_def_use_pairs": [...]}}` where each element is `{{"count": int, "def_line": int, "use_line": int, "variable": str}}`. `variable` is the bare variable name (e.g. "foo"), `def_line`/`use_line` are absolute 1-based line numbers in `{TARGET_REL}` as it exists in the repository (parameters use 143 as def_line). `count` is the total number of observations of that exact (variable, def_line, use_line) triple summed over ALL invocations in ALL test methods of the class. Each triple appears exactly once (the count carries multiplicity); pairs never observed are omitted. Sort the list by `variable` (ascending, plain string comparison), then `def_line` ascending, then `use_line` ascending.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root_candidates = [os.getcwd(), os.path.abspath(os.path.join(here, "..", "..", ".."))]
    src_path = None
    for root in root_candidates:
        p = os.path.join(root, TARGET_REL)
        if os.path.isfile(p):
            src_path = p
            break
    if src_path is None:
        fail("target source not found")
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = find_function(tree)
    params, line_to_key, infos = build_model(func)

    invocations = read_invocations(args.trace_log, TARGET_REL)
    counts = analyze(invocations, params, func.lineno, line_to_key, infos)
    if not counts:
        fail("no def-use pairs observed")

    pairs = [
        {"count": c, "def_line": dl, "use_line": ul, "variable": v}
        for (v, dl, ul), c in sorted(counts.items())
    ]
    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={len(invocations)} pairs={len(pairs)}")
    for p in pairs:
        print(f"  {p['variable']:>16} {p['def_line']:>4} -> {p['use_line']:>4}  x{p['count']}")


if __name__ == "__main__":
    main()
