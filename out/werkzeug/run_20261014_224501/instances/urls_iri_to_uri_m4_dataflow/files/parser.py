"""Trace -> oracle.json for urls_iri_to_uri_m4_dataflow (M4_DataFlow)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/werkzeug/urls.py"
TARGET_NAME = "iri_to_uri"
TRACKED = ("iri", "parts", "path", "query", "fragment", "netloc", "auth", "password")

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = """\
Test file: werkzeug_qa/urls_iri_to_uri_m4_dataflow/files/testcase.py
Test class: IriToUriFlowTest (run ALL 12 of its test methods, e.g. with
`pytest werkzeug_qa/urls_iri_to_uri_m4_dataflow/files/testcase.py::IriToUriFlowTest`;
each method is identified by its pytest id
`werkzeug_qa/urls_iri_to_uri_m4_dataflow/files/testcase.py::IriToUriFlowTest::<method>`).

Target function: `werkzeug.urls.iri_to_uri`, defined in `src/werkzeug/urls.py`
(the `def` line is line 116; the body's first statement `parts = urlsplit(iri)`
is line 144, the `return` is line 171). Line numbers are absolute, 1-based, in
that file as it exists in the repository.

Question: over ALL invocations of `iri_to_uri` during the whole test class
(an invocation = one call of the function; counts are summed over every
invocation in every test method of the class), report every observed def-use
pair of the tracked local variables together with how many times it was
observed.

Definitions:
- Tracked variables: exactly the eight local names `iri`, `parts`, `path`,
  `query`, `fragment`, `netloc`, `auth`, `password`. Module globals/callables
  (`urlsplit`, `quote`, `urlunsplit`) are NOT tracked, and attribute accesses
  such as `parts.hostname` count only as a use of the name `parts`.
- Def: the parameter `iri` is defined at the `def` line (116) on entry of each
  invocation. Every assignment statement `x = ...` to a tracked name defines it
  at the line of that statement (each statement in this function fits on one
  line). The right-hand side is evaluated before the assignment, so in a
  statement like `x = f"{x}..."` the read of `x` sees the PREVIOUS def of `x`,
  and the new def only affects later statements.
- Use: any read (load) of a tracked name in an executed statement, attributed
  to the line of that statement. For an `if` statement, only reads in its
  condition count, attributed to the line of the `if`. Reads inside f-strings
  and inside the tuple passed to `urlunsplit` on the return line count as uses.
  If one statement execution reads the same variable more than once, that is a
  single observation (e.g. a hypothetical `y = (a, a.b)` yields one use of `a`).
- Observation: one execution of a statement that reads a tracked variable,
  paired with the def that reaches it at that moment, i.e. the most recent def
  of that variable executed earlier in the same invocation. Defs never carry
  over between invocations. `count` = number of such observations of that exact
  (variable, def_line, use_line) triple, summed across all invocations in all
  test methods. Pairs never observed are omitted (no zero counts).

Answer format: a JSON object with a single key `observed_def_use_pairs`, a list
of objects with exactly the keys `variable` (str, the bare variable name),
`def_line` (int), `use_line` (int), `count` (int, >= 1). Each
(variable, def_line, use_line) triple appears at most once. Sort the list by
`variable` ascending (plain string comparison), then `def_line` ascending, then
`use_line` ascending.
"""

TEMPLATE = {
    "observed_def_use_pairs": [
        {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
    ]
}


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _names(node: ast.AST, ctx) -> set[str]:
    return {
        n.id
        for n in ast.walk(node)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ctx) and n.id in TRACKED
    }


def build_line_table(src_path: Path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    func = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_NAME:
            func = node
    if func is None:
        fail(f"{TARGET_NAME} not found in {src_path}")
    table: dict[int, tuple[set[str], set[str]]] = {}

    def visit(stmts):
        for st in stmts:
            if isinstance(st, ast.If):
                table[st.lineno] = (_names(st.test, ast.Load), set())
                visit(st.body)
                visit(st.orelse)
            elif isinstance(st, ast.Assign):
                uses = _names(st.value, ast.Load)
                for t in st.targets:
                    uses |= _names(t, ast.Load)
                defs = set()
                for t in st.targets:
                    defs |= _names(t, ast.Store)
                table[st.lineno] = (uses, defs)
            elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
                continue  # docstring
            else:
                table[st.lineno] = (_names(st, ast.Load), _names(st, ast.Store))

    visit(func.body)
    params = {a.arg for a in func.args.args}
    return func.lineno, params, table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=TARGET_REL)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file():
        fail(f"trace log missing: {trace}")
    text = trace.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    def_line, params, table = build_line_table(Path(args.source))

    counts: Counter = Counter()
    reaching: dict[str, int] | None = None
    n_calls = 0
    n_lines = 0
    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_REL):
            continue
        if not m.group("func").endswith("." + TARGET_NAME):
            continue
        ev = m.group("event")
        ln = int(m.group("line"))
        if ev == "call":
            if reaching is not None:
                fail("nested/unterminated invocation of target")
            n_calls += 1
            reaching = {p: def_line for p in params}
        elif ev == "line":
            if reaching is None:
                fail(f"line event outside invocation: {raw}")
            if ln not in table:
                fail(f"unexpected executed line {ln}")
            n_lines += 1
            uses, defs = table[ln]
            for v in sorted(uses):
                if v not in reaching:
                    fail(f"use of {v} at {ln} with no reaching def")
                counts[(v, reaching[v], ln)] += 1
            for v in defs:
                reaching[v] = ln
        elif ev == "return":
            if reaching is None:
                fail("return without call")
            reaching = None
        elif ev == "exception":
            fail(f"unexpected exception event in target: {raw}")

    if n_calls == 0 or n_lines == 0:
        fail("zero target events in trace")
    if reaching is not None:
        fail("trace ended mid-invocation")

    answer = {
        "observed_def_use_pairs": [
            {"count": c, "def_line": d, "use_line": u, "variable": v}
            for (v, d, u), c in sorted(counts.items())
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
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"invocations={n_calls} line_events={n_lines} pairs={len(counts)}")
    for (v, d, u), c in sorted(counts.items()):
        print(f"  {v:9s} {d} -> {u}: {c}")


if __name__ == "__main__":
    main()
