"""Derive the M4 oracle (def-use pairs with counts) for get_canonical_ordering from the trace log."""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

REL_FILE = "networkx/algorithms/planar_drawing.py"
FUNC_NAME = "get_canonical_ordering"
QUALNAME = f"networkx.algorithms.planar_drawing.{FUNC_NAME}"
TEST_PATH = "networkx_qa/planar_drawing_get_canonical_ordering_m4_dataflow/files/testcase.py"
TEST_CLASS = "TestPlanarLayoutScenarios"
TRACKED = ("nbr", "next_nbr", "prev_nbr", "v", "w", "wp", "wp_wq", "wq")

LINE_RE = re.compile(
    r"\s(?P<file>/\S+?\.py):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = f"""\
Test: `{TEST_PATH}`, class `{TEST_CLASS}`. The answer aggregates over ALL test methods of this class (every `test_*` method, i.e. every pytest id of the form `{TEST_PATH}::{TEST_CLASS}::<method>`), run in one pytest session.

Target function: the module-level function `{FUNC_NAME}` defined in `{REL_FILE}` (dotted name `{QUALNAME}`). Only the target's own frame is analysed. The bodies of the nested helper functions `is_outer_face_nbr` and `is_on_outer_face` are separate frames and are NOT analysed (calling them from a statement of the target does not create uses or defs beyond what is written lexically in that calling statement); the nested `def` statements themselves are statements of the target that define the helper names (which are not tracked).

Tracked variables (local names of the target; nothing else is tracked): {", ".join(f"`{v}`" for v in TRACKED)}.

Question: over ALL invocations of the target during the whole test class, which dynamic def-use pairs of the tracked variables are observed, and how many times is each observed?

Definitions:
- Invocation = one call of the target (one new frame), however it is reached (the tests never call it directly). Invocations are analysed independently: a definition never reaches across invocations.
- Execution model: consider the chronological sequence of statement executions in the target's own frame. Each statement is identified by the absolute, 1-based line number in `{REL_FILE}` (as it exists in the repository) on which the statement begins; for compound statements (`if`/`elif`/`while`/`for`) this is the line of the header keyword, and the header comprises only the condition (or the `for` target and iterable), not the body. `else:` lines are not statements. The `def` line of the target never appears as a use or def line (no parameter is tracked).
- Def: a statement defines a variable when it binds that name as a plain assignment target. A `for` header defines its target variable each time it executes AND binds a new item (i.e. the next statement executed is inside that loop's body); the execution of a `for` header that finds the iterator exhausted defines nothing. Item assignment/augmented item assignment such as `d[x] = y` or `d[x] -= 1` is NOT a def of `d` or `x` (both are uses).
- Use: a statement execution uses every tracked variable whose name appears in a read (load) position anywhere in that statement's source text (for a compound statement: anywhere in its header), counted once per statement execution even if the name appears several times in the statement. This is lexical: a read counts even if short-circuiting means the subexpression is never evaluated at runtime. `for` headers use the names in their iterable expression on every execution of the header (including the exhausting one); `while` headers use the names in their condition on every evaluation.
- Within one statement, all uses happen before any def.
- Observation: one execution of a statement that uses `variable`, together with the def of `variable` reaching it, i.e. the most recent def of `variable` executed earlier in the same invocation, identified by that def statement's line (`def_line`). A use inside a loop body therefore yields one observation per execution. `count` is the number of observations of the triple `(variable, def_line, use_line)`, summed over all invocations in all test methods of the class.

Answer format: JSON object `{{"observed_def_use_pairs": [...]}}`, each element an object with exactly the keys `variable` (str, the bare variable name), `def_line` (int), `use_line` (int), `count` (int, >= 1). Each triple appears exactly once (the count carries the multiplicity); triples never observed are absent. Sort ascending by `variable` (plain string order), then `def_line`, then `use_line`.
"""

TEMPLATE = {
    "observed_def_use_pairs": [
        {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
    ]
}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_target(tree):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            return node
    fail("target function not found in source")


def names(nodes, ctx):
    out = set()
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ctx) and sub.id in TRACKED:
                out.add(sub.id)
    return out


class Stmt:
    def __init__(self, start, end, uses, defs, body_range=None):
        self.start = start
        self.end = end
        self.uses = uses
        self.defs = defs
        self.body_range = body_range


def collect_statements(body, out):
    for node in body:
        if isinstance(node, (ast.If, ast.While)):
            out.append(Stmt(node.lineno, node.test.end_lineno, names([node.test], ast.Load), set()))
            collect_statements(node.body, out)
            collect_statements(node.orelse, out)
        elif isinstance(node, ast.For):
            end = max(node.target.end_lineno, node.iter.end_lineno)
            body_range = (node.body[0].lineno, node.body[-1].end_lineno)
            out.append(
                Stmt(
                    node.lineno,
                    end,
                    names([node.iter], ast.Load),
                    names([node.target], ast.Store),
                    body_range,
                )
            )
            collect_statements(node.body, out)
            collect_statements(node.orelse, out)
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list or node.args.defaults or node.args.kw_defaults:
                fail(f"unsupported nested def at line {node.lineno}")
            # Nested helper: the def statement binds an untracked name only.
            out.append(Stmt(node.lineno, node.lineno, set(), set()))
        elif isinstance(node, (ast.With, ast.Try, ast.ClassDef, ast.Match)):
            fail(f"unsupported compound statement at line {node.lineno}")
        else:
            if isinstance(node, (ast.AugAssign,)) and isinstance(node.target, ast.Name):
                if node.target.id in TRACKED:
                    fail("augmented assignment to a tracked name is not modelled")
            out.append(Stmt(node.lineno, node.end_lineno, names([node], ast.Load), names([node], ast.Store)))


def build_model(src_path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    func = find_target(tree)
    for node in ast.walk(func):
        if isinstance(node, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in TRACKED and isinstance(sub.ctx, ast.Store):
                    fail("tracked name bound in nested scope")
    body = func.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    stmts = []
    collect_statements(body, stmts)
    line_map = {}
    for st in stmts:
        if st.start != st.end:
            fail(f"multi-line statement at {st.start} not expected")
        line_map[st.start] = st
    return func.lineno, line_map


def read_invocations(trace_path, def_line):
    if not trace_path.exists():
        fail(f"trace log missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        fail(f"trace log empty: {trace_path}")
    invocations = []
    current = None
    n_events = 0
    for raw in text.splitlines():
        m = LINE_RE.search(raw)
        if not m or m.group("func") != QUALNAME:
            continue
        if not m.group("file").replace("\\", "/").endswith(REL_FILE):
            continue
        n_events += 1
        event = m.group("event")
        line = int(m.group("line"))
        if event == "call":
            if line != def_line:
                fail(f"unexpected call event at line {line}")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                fail("line event before any invocation start")
            current.append(line)
        elif event == "return":
            current = None
    if n_events == 0 or not invocations:
        fail("no events for the target function in the trace")
    return invocations


def analyse(invocations, line_map):
    counts = Counter()
    for lines in invocations:
        seq = []
        for ln in lines:
            st = line_map.get(ln)
            if st is None:
                fail(f"executed line {ln} not mapped to a statement")
            seq.append(st)
        reaching = {}
        for i, st in enumerate(seq):
            for var in sorted(st.uses):
                if var not in reaching:
                    fail(f"use of {var} at {st.start} without reaching def")
                counts[(var, reaching[var], st.start)] += 1
            defs = st.defs
            if st.body_range is not None:
                nxt = seq[i + 1] if i + 1 < len(seq) else None
                lo, hi = st.body_range
                if nxt is None or not (lo <= nxt.start <= hi):
                    defs = set()
            for var in defs:
                reaching[var] = st.start
    return sorted(counts.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[3]
    src = root / REL_FILE
    if not src.exists():
        src = Path.cwd() / REL_FILE
    if not src.exists():
        fail(f"target source not found: {REL_FILE}")

    def_line, line_map = build_model(src)
    invocations = read_invocations(Path(args.trace_log), def_line)
    pairs = analyse(invocations, line_map)
    if not pairs:
        fail("no def-use pairs observed")

    answer = {
        "observed_def_use_pairs": [
            {"count": c, "def_line": d, "use_line": u, "variable": v}
            for (v, d, u), c in pairs
        ]
    }
    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} pairs={len(pairs)}")
    for (v, d, u), c in pairs:
        print(f"{v:10s} {d} {u} {c}")


if __name__ == "__main__":
    main()
