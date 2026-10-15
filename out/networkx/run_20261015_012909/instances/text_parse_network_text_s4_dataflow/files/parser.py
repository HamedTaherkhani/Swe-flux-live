"""Derive the S4 oracle (dynamic def-use pairs) for _parse_network_text from the trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REL_FILE = "networkx/readwrite/text.py"
FUNC_NAME = "_parse_network_text"
QUALNAME = f"networkx.readwrite.text.{FUNC_NAME}"
TEST_PATH = "networkx_qa/text_parse_network_text_s4_dataflow/files/testcase.py"
TEST_CLASS = "TestParseNetworkTextRoundTrips"
TEST_METHOD = "test_parse_many_renderings"
TRACKED = (
    "curr",
    "edges",
    "glyphs",
    "is_ascii",
    "is_directed",
    "is_empty",
    "line",
    "lines",
    "node",
    "node_part",
    "nodes",
    "prefix",
    "prev",
    "stack",
)

LINE_RE = re.compile(
    r"\s(?P<file>/\S+?\.py):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = f"""\
Test: `{TEST_PATH}`, class `{TEST_CLASS}`, its single test method `{TEST_METHOD}` (pytest id `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}`).

Target function: the module-level function `{FUNC_NAME}` defined in `{REL_FILE}` (dotted name `{QUALNAME}`). Only the target's own frame counts; no other function is analysed. Code in generator expressions and list comprehensions written inside the target is attributed to the statement containing it as described below; the body of the nested `class ParseStackFrame` is not part of the analysis (only the `class` statement itself is).

Tracked variables (local names of the target; nothing else is tracked): {", ".join(f"`{v}`" for v in TRACKED)}.

Question: over ALL invocations of the target during this test method, which dynamic def-use pairs are observed for the tracked variables?

Definitions:
- Invocation = one call of the target, 1-based in chronological order. Each invocation is analysed independently: a definition never reaches across invocations.
- Execution model: consider the chronological sequence of statement executions in the target's own frame. Each statement is identified by the absolute, 1-based line number (in `{REL_FILE}` as it exists in the repository) on which the statement begins; for compound statements (`if`/`elif`/`while`/`for`) this is the line of the header keyword, and the header comprises only the condition (or the `for` target and iterable), not the body. `try:` and `except ...:` headers are statements that read and bind no tracked name; the `else:` keyword of a `try`/`if` is not a statement. A `class` statement is one statement at its `class` line. A multi-line statement or header is one statement executed once, attributed to its first line.
- Def: the parameter `lines` is defined at the line of the `def` keyword when an invocation starts. A statement defines a variable when it binds that name: plain assignment targets (including each name in a tuple-unpacking target such as `a, b = ...`) and augmented assignment targets. A `for` header defines its target variable each time it executes AND binds a new item (i.e. the next statement executed is in the loop body); the execution of the header that finds the iterator exhausted defines nothing. Method calls that mutate an object (e.g. `xs.append(v)`, `xs.pop()`) and item assignment `d[k] = v` are NOT defs of that object's name (they are uses of it). Names bound only inside a comprehension/generator expression (its own `for` targets) are comprehension-local and never tracked; none of the tracked names is bound by such a construct.
- Use: a statement execution uses every tracked variable whose name appears in a read (load) position anywhere in that statement's source text (for a compound statement: anywhere in its header), including inside generator expressions and list comprehensions written in that statement. This is lexical: a read counts even if short-circuiting or an empty iterable means the subexpression is never evaluated at runtime. `for` headers count as using the names in their iterable expression on every execution of the header (including the exhausting one).
- Within one statement, all uses happen before any def. Augmented assignment (`x op= expr`) is both a use (of the reaching def) and a new def of `x` on that line (the target contains none, but this is the rule).
- Pair: `(variable, def_line, use_line)` is observed when, at some execution of the statement at `use_line` that uses `variable`, the most recent def of `variable` in the same invocation was made at `def_line`.

Answer format: JSON object `{{"observed_def_use_pairs": [...]}}`, each element an object with exactly the keys `variable` (str, the bare variable name), `def_line` (int), `use_line` (int). Report each distinct triple once (deduplicated across all executions and invocations). Sort ascending by `variable` (plain string order), then `def_line`, then `use_line`.
"""

TEMPLATE = {
    "observed_def_use_pairs": [{"def_line": "int", "use_line": "int", "variable": "str"}]
}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_target(tree):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME:
            return node
    fail("target function not found in source")


NESTED_SCOPES = (ast.Lambda, ast.GeneratorExp, ast.SetComp, ast.ListComp, ast.DictComp)


def check_nested_bindings(func):
    for node in ast.walk(func):
        if isinstance(node, NESTED_SCOPES):
            for sub in ast.walk(node):
                if isinstance(sub, ast.comprehension):
                    for t in ast.walk(sub.target):
                        if isinstance(t, ast.Name) and t.id in TRACKED:
                            fail(f"tracked name {t.id} bound in nested scope")
                if isinstance(sub, ast.arg) and sub.arg in TRACKED:
                    fail(f"tracked name {sub.arg} bound as lambda arg")


def names(nodes, ctx):
    out = set()
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ctx) and sub.id in TRACKED:
                out.add(sub.id)
    return out


class Stmt:
    def __init__(self, node, start, end, uses, defs, body_range=None):
        self.node = node
        self.start = start
        self.end = end
        self.uses = uses
        self.defs = defs
        self.body_range = body_range  # for `for` loops: (first, last) body lines


def collect_statements(body, out):
    for node in body:
        if isinstance(node, (ast.If, ast.While)):
            out.append(
                Stmt(node, node.lineno, node.test.end_lineno, names([node.test], ast.Load), set())
            )
            collect_statements(node.body, out)
            collect_statements(node.orelse, out)
        elif isinstance(node, ast.For):
            end = max(node.target.end_lineno, node.iter.end_lineno)
            body_range = (node.body[0].lineno, node.body[-1].end_lineno)
            out.append(
                Stmt(
                    node,
                    node.lineno,
                    end,
                    names([node.iter], ast.Load),
                    names([node.target], ast.Store),
                    body_range,
                )
            )
            collect_statements(node.body, out)
            collect_statements(node.orelse, out)
        elif isinstance(node, ast.Try):
            out.append(Stmt(node, node.lineno, node.lineno, set(), set()))
            collect_statements(node.body, out)
            for h in node.handlers:
                end = h.type.end_lineno if h.type is not None else h.lineno
                out.append(Stmt(h, h.lineno, end, set(), set()))
                collect_statements(h.body, out)
            collect_statements(node.orelse, out)
            collect_statements(node.finalbody, out)
        elif isinstance(node, ast.ClassDef):
            # class body runs in its own frame; the statement binds only the class name
            out.append(Stmt(node, node.lineno, node.end_lineno, set(), set()))
        elif isinstance(node, (ast.With, ast.FunctionDef, ast.Match, ast.TryStar)):
            fail(f"unsupported compound statement at line {node.lineno}")
        else:
            uses = names([node], ast.Load)
            defs = names([node], ast.Store)
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                if node.target.id in TRACKED:
                    uses.add(node.target.id)
            out.append(Stmt(node, node.lineno, node.end_lineno, uses, defs))


def build_model(src_path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    func = find_target(tree)
    check_nested_bindings(func)
    body = func.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # docstring
    stmts = []
    collect_statements(body, stmts)
    line_map = {}
    for st in stmts:
        for ln in range(st.start, st.end + 1):
            # innermost wins; statements collected outer-first, headers never overlap bodies
            line_map[ln] = st
    params = {a.arg for a in func.args.args} & set(TRACKED)
    return func.lineno, line_map, params


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
    if n_events == 0 or not invocations:
        fail("no events for the target function in the trace")
    return invocations


def analyse(invocations, def_line, line_map, params):
    pairs = set()
    for lines in invocations:
        seq = []
        for ln in lines:
            st = line_map.get(ln)
            if st is None:
                fail(f"executed line {ln} not mapped to a statement")
            if seq and seq[-1] is st:
                continue  # several line events for one multi-line statement
            seq.append(st)
        reaching = {p: def_line for p in params}
        for i, st in enumerate(seq):
            for var in sorted(st.uses):
                if var not in reaching:
                    fail(f"use of {var} at {st.start} without reaching def")
                pairs.add((var, reaching[var], st.start))
            defs = st.defs
            if st.body_range is not None:
                nxt = seq[i + 1] if i + 1 < len(seq) else None
                lo, hi = st.body_range
                if nxt is None or not (lo <= nxt.start <= hi):
                    defs = set()
            for var in defs:
                reaching[var] = st.start
    return sorted(pairs)


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

    def_line, line_map, params = build_model(src)
    invocations = read_invocations(Path(args.trace_log), def_line)
    pairs = analyse(invocations, def_line, line_map, params)
    if not pairs:
        fail("no def-use pairs observed")

    answer = {
        "observed_def_use_pairs": [
            {"def_line": d, "use_line": u, "variable": v} for v, d, u in pairs
        ]
    }
    oracle = {
        "question_kind": "S4_DataFlow",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={len(invocations)} pairs={len(pairs)}")
    print(json.dumps(answer, indent=1))


if __name__ == "__main__":
    main()
