"""Trace -> oracle.json for request_load_form_data_m4_dataflow (M4_DataFlow)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_REL = "src/werkzeug/wrappers/request.py"
TARGET_QUALNAME = "Request._load_form_data"
TRACKED = ("self", "warnings", "stream", "result")

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = """\
Test file: werkzeug_qa/request_load_form_data_m4_dataflow/files/testcase.py
Test class: LoadFormDataFlowTest (run ALL of its test methods, e.g. with
`pytest werkzeug_qa/request_load_form_data_m4_dataflow/files/testcase.py::LoadFormDataFlowTest`).

Target function: `werkzeug.wrappers.request.Request._load_form_data`, defined in
`src/werkzeug/wrappers/request.py` (the `def` line is line 396). The test never
calls it by name; it is reached through `Request.form`, `Request.files`,
`Request.values`, `Request.data` and `Request.get_data(...)`, including from the
Request subclasses defined in the test file (none of them overrides
`_load_form_data` itself, so every execution runs the code at that location).

Question: over ALL invocations of this function during the whole test class
(summed over every test method; an invocation = one call of the function), report
every observed def-use pair of the tracked local variables together with how many
times it was observed.

Definitions:
- Tracked variables: exactly the four local names `self`, `warnings`, `stream`,
  `result`. Module globals and builtins (`Request`, `ImmutableMultiDict`, `type`,
  `DeprecationWarning`, ...) and attributes (`self.form`, `self.files`, ...) are
  NOT tracked variables.
- Def: the parameter `self` is defined at the `def` line (396) on entry of each
  invocation. `import warnings` defines `warnings` at the line of that import
  statement. `stream = ...` / `result = ...` define the variable at the line of
  the assignment statement. A def only takes effect if its statement completes
  (an assignment whose right-hand side raises defines nothing). Assigning to an
  attribute such as `self.form = ...` or `self.form, self.files = result` is NOT a
  def of `self`; it is a USE of `self` (and of `result` on the right-hand side).
- Use: any read (load) of a tracked name in an executed statement, including
  `self` inside `type(self)`, `self.__dict__`, `self.<attr> = ...` targets and
  call arguments. A use is attributed to the line where its statement begins; for
  an `if` statement, uses in its condition are attributed to the line of the `if`
  keyword, even when the condition spans several physical lines (e.g. a
  parenthesized condition starting on line N and continuing on N+1, N+2 is
  reported as use_line N). Likewise a multi-line call statement is reported at
  the line where the statement begins.
- Observation: one execution of a statement that reads the variable, paired with
  the def that reaches it at that moment (the most recent completed def of that
  variable in the same invocation). If a statement reads the same variable
  several times (e.g. `self.x = self.y()`), that is still ONE observation for
  that execution. A statement that starts executing but raises still counts its
  uses. Flows never cross invocations.
- count = total number of observations of that exact (variable, def_line,
  use_line) triple, summed across all invocations in all test methods of the
  class. Pairs never observed are omitted (no zero counts).
- The function body contains no loops, augmented assignments, comprehensions or
  try blocks; the docstring is not a statement and never appears as a use line.
- Line numbers are absolute, 1-based line numbers in
  src/werkzeug/wrappers/request.py as it exists in the repository.

Output format: a JSON object
{"observed_def_use_pairs": [{"count": int, "def_line": int, "use_line": int, "variable": str}, ...]}
where `variable` is the bare name (e.g. "stream"). Each (variable, def_line,
use_line) triple appears exactly once. Sort the list by variable (ascending,
plain string order), then def_line ascending, then use_line ascending.
"""

TEMPLATE = {
    "observed_def_use_pairs": [
        {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
    ]
}


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


class Stmt:
    def __init__(self, node: ast.stmt):
        self.lineno = node.lineno
        if isinstance(node, (ast.If, ast.While)):
            self.span = (node.lineno, node.body[0].lineno - 1)
            scan = [node.test]
        else:
            self.span = (node.lineno, node.end_lineno)
            scan = [node]
        self.uses = set()
        for root in scan:
            for sub in ast.walk(root):
                if (
                    isinstance(sub, ast.Name)
                    and isinstance(sub.ctx, ast.Load)
                    and sub.id in TRACKED
                ):
                    self.uses.add(sub.id)
        self.defs = set()
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                        if sub.id in TRACKED:
                            self.defs.add(sub.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                if name in TRACKED:
                    self.defs.add(name)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.For, ast.With)):
            die(f"unexpected statement kind at line {node.lineno}")


def load_function(src_path: Path):
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "Request":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "_load_form_data":
                    return fn
    die("could not locate Request._load_form_data in source")


def collect_stmts(fn: ast.FunctionDef) -> list[Stmt]:
    out: list[Stmt] = []

    def visit(body):
        for node in body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue  # docstring
            out.append(Stmt(node))
            for field in ("body", "orelse"):
                if isinstance(node, (ast.If, ast.While)):
                    visit(getattr(node, field))

    visit(fn.body)
    return out


def parse_invocations(trace_path: Path, src_suffix: str):
    invocations = []
    current = None
    n_events = 0
    with trace_path.open(encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if not m["file"].replace("\\", "/").endswith(src_suffix):
                continue
            if not m["func"].endswith("." + TARGET_QUALNAME):
                continue
            n_events += 1
            ev, line = m["event"], int(m["line"])
            if ev == "call":
                if current is not None:
                    die("re-entrant invocation of target not supported")
                current = {"lines": [], "exc_lines": []}
            elif current is None:
                die(f"event {ev} outside an invocation at line {line}")
            elif ev == "line":
                current["lines"].append(line)
            elif ev == "exception":
                current["exc_lines"].append(line)
            elif ev == "return":
                invocations.append(current)
                current = None
    if current is not None:
        die("trace ended inside an invocation")
    return invocations, n_events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default=None)
    args = ap.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        die(f"trace log not found: {trace_path}")
    if trace_path.stat().st_size == 0:
        die(f"trace log is empty: {trace_path}")

    here = Path(__file__).resolve()
    src = Path(args.source) if args.source else None
    if src is None:
        for base in [Path.cwd(), *here.parents]:
            cand = base / TARGET_REL
            if cand.is_file():
                src = cand
                break
    if src is None or not src.is_file():
        die("target source file not found")

    fn = load_function(src)
    def_line = fn.lineno
    stmts = collect_stmts(fn)

    invocations, n_events = parse_invocations(trace_path, TARGET_REL)
    if n_events == 0 or not invocations:
        die("no events for the target function in the trace")

    def stmt_for_line(line: int) -> Stmt:
        best = None
        for st in stmts:
            lo, hi = st.span
            if lo <= line <= hi:
                if best is None or (lo, -hi) > (best.span[0], -best.span[1]):
                    best = st
        if best is None:
            die(f"executed line {line} does not map to a statement")
        return best

    counts: Counter = Counter()
    total_lines = 0
    for inv in invocations:
        total_lines += len(inv["lines"])
        executed: list[Stmt] = []
        for line in inv["lines"]:
            st = stmt_for_line(line)
            if st in executed:
                if executed[-1] is not st:
                    die("statement re-executed non-consecutively (loop?)")
                continue
            executed.append(st)
        if [s.lineno for s in executed] != sorted(s.lineno for s in executed):
            die("unexpected non-monotonic statement order")
        failed = {stmt_for_line(l).lineno for l in inv["exc_lines"]}
        reaching = {"self": def_line}
        for st in executed:
            for var in sorted(st.uses):
                if var not in reaching:
                    die(f"use of {var} at {st.lineno} without reaching def")
                counts[(var, reaching[var], st.lineno)] += 1
            if st.lineno not in failed:
                for var in st.defs:
                    reaching[var] = st.lineno

    pairs = [
        {"count": c, "def_line": d, "use_line": u, "variable": v}
        for (v, d, u), c in sorted(counts.items())
    ]
    if not pairs:
        die("no def-use pairs computed")

    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": {"observed_def_use_pairs": pairs},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"invocations={len(invocations)} line_events={total_lines} "
        f"pairs={len(pairs)}"
    )
    print(json.dumps(oracle["oracle_answer"], indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
