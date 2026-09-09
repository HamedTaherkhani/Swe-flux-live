"""Parse the sys.settrace log into oracle.json for instance
pipeline_group_by_namespace_m4_dataflow (M4_DataFlow).

The answer is the set of all unique observed def-use pairs, over every
invocation of kedro.pipeline.pipeline.Pipeline._group_by_namespace during
the test run, for the eight tracked local names.

Method: the executed-line sequence per invocation is recovered from the
trace; per-line def/use sets for the tracked names are recovered from a
static AST pass over the target's source (a Name with Load context is a use
on its own physical line; a Name with Store/Del context is a def on its own
physical line; a for-loop header target is a def on the header line; an
augmented-assignment target counts as both; parameters are defs on the
`def` line; subscript/attribute stores are uses of the base name, not
defs).  Each invocation is then simulated: for every executed line, uses
are paired with the currently reaching def, then defs update the reaching
def.  Pairs are deduplicated across the whole run and sorted by
(variable, def_line, use_line).
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/pipeline/pipeline.py"
TARGET_FUNC = "kedro.pipeline.pipeline._group_by_namespace"
TARGET_FUNC_NAME = "_group_by_namespace"
TRACKED_VARS = [
    "self",
    "grouped_nodes_map",
    "node",
    "key",
    "dependencies",
    "unique_dependencies",
    "parent",
    "parent_key",
]

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/pipeline_group_by_namespace_m4_dataflow/files/testcase.py::TestGroupByNamespaceDataFlow::test_traced_run`
is executed, the method
`kedro.pipeline.pipeline.Pipeline._group_by_namespace`
(defined in the repository file `kedro/pipeline/pipeline.py`) is invoked
three times, indirectly: the test builds three `Pipeline` objects
programmatically and calls the public method
`kedro.pipeline.pipeline.Pipeline.group_nodes_by` with
`group_by="namespace"` once on each of them, and that dispatcher's body
calls the target method exactly once per call. The three pipelines are
wired so that the target's branches and loops are exercised in different
combinations across the three invocations: namespaced and bare
(namespace-less) nodes on both the node side and the parent side, nested
namespaces whose top-level keys collide, nodes with zero parents, parents
sharing the node's own group key, and fan-in nodes whose several parents
collapse to the same dependency key.

Task: report ALL unique observed def-use pairs, over ALL three invocations
of `kedro.pipeline.pipeline.Pipeline._group_by_namespace` during this test
run, for exactly these eight local names of the target method: `self`,
`grouped_nodes_map`, `node`, `key`, `dependencies`, `unique_dependencies`,
`parent`, `parent_key`.

Definitions and conventions:

- Line numbers are absolute, 1-based, in the file
  `kedro/pipeline/pipeline.py` as it exists on disk in this repository.
- A "def" of a tracked name is a binding of that bare name: a simple
  assignment to the name (e.g. `x = ...`), a `for` loop header binding
  (`for x in ...:` redefines `x` on the header line once per iteration),
  or a parameter binding. The parameter `self` counts as defined at the
  line of the method's `def` statement, and that def is in effect from the
  moment the invocation begins, before any line of the body executes.
- A "use" of a tracked name is any read of the name: any occurrence of the
  bare name in load position, including as the base object of a subscript
  or attribute access and including the iterable expression of a `for`
  header.
- Subscript or attribute stores such as `d[key] = value` do NOT redefine
  the base name `d` (they mutate the object it refers to); the occurrence
  of `d` in such a statement is a use of `d` (and any tracked names among
  the subscript/key/value expressions are uses as well). Method-call
  statements such as `x.append(y)` or `s.add(y)` are uses of `x`/`s` and
  of `y`, not defs.
- Augmented assignment (`x += 1`) reads then writes: it would count BOTH
  as a use of the previously reaching def AND as a new def of `x`, both on
  that line. (The target body contains no augmented assignment; the rule
  is stated for completeness.)
- Only the eight names enumerated above are tracked. Any other local names
  are not tracked. The target's body contains one `lambda` used as a sort
  key; the lambda's own parameter and body belong to a separate scope and
  are not tracked, and the lambda's execution runs in a separate frame
  that contributes nothing.
- A use or def is attributed to the physical line on which the name
  textually appears, even when the containing statement spans several
  physical lines: for example, a name appearing on a continuation line of
  a multi-line call or a multi-line assignment is attributed to that
  continuation line, not to the line where the statement begins.
- A pair {variable, def_line, use_line} is OBSERVED if, during some
  invocation of the target in this test run, the line use_line actually
  executes (fires an executed-line event, equivalent to a `line` event of
  `sys.settrace`, for the target method's own frame) and at that moment
  the reaching def of `variable` is def_line — i.e. def_line is the most
  recent def of that variable executed earlier within the SAME invocation
  (the parameter binding at the `def` line counts as executed at
  invocation start), with no other def of that variable executed in
  between. Note that on this interpreter a multi-line statement may fire
  executed-line events both on the line where the statement begins and on
  continuation lines as sub-expressions evaluate; a pair is observed only
  when the use's own physical line fires.
- When a single executed line both uses and defines the same tracked name
  (e.g. `key = <expr using key>`), the uses on that line are paired with
  the def that was reaching BEFORE the line executed, and only afterwards
  does the line's def become the new reaching def. Uses and defs of
  different names on the same line are independent.
- Only the target method's own frame counts. Functions and constructors
  the target calls (including the grouping-record constructor and the
  `sorted`/`set`/`list` builtins) run in separate frames or no Python
  frame at all; their internal lines contribute nothing. However, the
  target's own lines performing such calls (including the lines holding
  the argument expressions) DO count normally. The line containing the
  target's `return` statement also counts: it is a use of every tracked
  name read by the return expression.
- Aggregation and deduplication: collect the observed pairs from all three
  invocations into one set; pairs that are observed multiple times (within
  one invocation, across loop iterations, or across invocations) are
  reported only once.
- Invocation counting (for reference): one invocation is one entry into
  the target method during the test run, counted 1-based in chronological
  order of method entry; this test run produces exactly three invocations,
  and the answer aggregates over all of them.

Answer format: a JSON object with exactly one key, `observed_def_use_pairs`,
whose value is a list of objects, one per unique observed pair. Each object
has exactly three keys: `variable` (a JSON string, one of the eight tracked
names), `def_line` (a JSON integer) and `use_line` (a JSON integer). The
list is sorted ascending by `variable` (lexicographic), then by `def_line`,
then by `use_line`.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def build_def_use_maps(source_path):
    """Return (def_line, param_names, uses, defs) for the target method.

    uses/defs map physical line number -> set of tracked variable names.
    """
    try:
        with open(source_path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=source_path)
    except OSError as exc:
        fail(f"could not read target source: {exc}")

    funcdef = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == TARGET_FUNC_NAME:
            funcdef = node
            break
    if funcdef is None:
        fail(f"function {TARGET_FUNC_NAME} not found in {source_path}")

    params = [a.arg for a in funcdef.args.args + funcdef.args.kwonlyargs]
    if funcdef.args.vararg:
        params.append(funcdef.args.vararg.arg)
    if funcdef.args.kwarg:
        params.append(funcdef.args.kwarg.arg)

    tracked = set(TRACKED_VARS)
    uses = {}
    defs = {}

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            if node is funcdef:
                self.generic_visit(node)
            # nested function bodies are separate scopes: skip them

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            pass

        def visit_ClassDef(self, node):
            pass

        def visit_Name(self, node):
            if node.id not in tracked:
                return
            if isinstance(node.ctx, ast.Load):
                uses.setdefault(node.lineno, set()).add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                defs.setdefault(node.lineno, set()).add(node.id)

        def visit_AugAssign(self, node):
            # reads the old binding, then writes a new one
            if isinstance(node.target, ast.Name) and node.target.id in tracked:
                uses.setdefault(node.target.lineno, set()).add(node.target.id)
            self.generic_visit(node)

    Visitor().visit(funcdef)
    return funcdef.lineno, params, uses, defs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo-root", default="/testbed")
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")

    invocations = []  # list of lists of executed line numbers
    current = None
    total_line_events = 0
    distinct_lines = set()

    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_FUNC:
                continue
            event = m.group("event")
            lineno = int(m.group("line"))
            if event == "call":
                if current is not None:
                    invocations.append(current)
                current = []
            elif event == "line":
                if current is None:
                    fail("line event encountered before any call event")
                current.append(lineno)
                total_line_events += 1
                distinct_lines.add(lineno)
            elif event in ("return", "exception"):
                if current is not None:
                    invocations.append(current)
                    current = None
    if current is not None:
        invocations.append(current)

    if not invocations:
        fail(f"no events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")

    def_line, params, uses, defs = build_def_use_maps(
        os.path.join(args.repo_root, TARGET_FILE_REL)
    )

    pairs = set()
    for executed_lines in invocations:
        last_def = {p: def_line for p in params if p in set(TRACKED_VARS)}
        for lineno in executed_lines:
            for var in sorted(uses.get(lineno, ())):
                if var in last_def:
                    pairs.add((var, last_def[var], lineno))
            for var in defs.get(lineno, ()):
                last_def[var] = lineno

    if not pairs:
        fail("no def-use pairs observed for tracked variables")

    uncovered = [v for v in TRACKED_VARS if not any(p[0] == v for p in pairs)]
    if uncovered:
        fail(f"tracked variables with zero observed pairs: {uncovered}")

    ordered = sorted(pairs, key=lambda p: (p[0], p[1], p[2]))

    print(f"invocations traced: {len(invocations)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"unique observed def-use pairs: {len(ordered)}")

    oracle_answer = {
        "observed_def_use_pairs": [
            {"variable": var, "def_line": dline, "use_line": uline}
            for var, dline, uline in ordered
        ]
    }
    template_answer = {
        "observed_def_use_pairs": [
            {"def_line": "int", "use_line": "int", "variable": "str"}
        ]
    }
    oracle = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
