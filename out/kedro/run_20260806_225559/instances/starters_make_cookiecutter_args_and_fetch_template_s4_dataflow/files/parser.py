"""Parse the sys.settrace log into oracle.json for instance
starters_make_cookiecutter_args_and_fetch_template_s4_dataflow (S4_DataFlow).

The answer is the set of all unique observed def-use pairs, over every
invocation of kedro.framework.cli.starters._make_cookiecutter_args_and_fetch_template
during the test run, for the eight tracked local variables.

Method: the executed-line sequence per invocation is recovered from the
trace; per-line def/use sets for the tracked names are recovered from a
static AST pass over the target's source (a Name with Load context is a use
on its own physical line; a Name with Store/Del context is a def on its own
physical line; an augmented-assignment target counts as both; parameters are
defs on the `def` line).  Each invocation is then simulated: for every
executed line, uses are paired with the currently reaching def, then defs
update the reaching def.  Pairs are deduplicated across the whole run and
sorted by (variable, def_line, use_line).
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/framework/cli/starters.py"
TARGET_FUNC = "kedro.framework.cli.starters._make_cookiecutter_args_and_fetch_template"
TARGET_FUNC_NAME = "_make_cookiecutter_args_and_fetch_template"
TRACKED_VARS = [
    "config",
    "checkout",
    "directory",
    "template_path",
    "cookiecutter_args",
    "tools",
    "example_pipeline",
    "starter_path",
]

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/starters_make_cookiecutter_args_and_fetch_template_s4_dataflow/files/testcase.py::TestCookiecutterArgsDataFlow::test_traced_run`
is executed, the function
`kedro.framework.cli.starters._make_cookiecutter_args_and_fetch_template`
(defined in the repository file `kedro/framework/cli/starters.py`) is invoked
eight times indirectly: the test invokes the callback of the `new` command
defined in the same module (the `new` command's body calls the target
function directly, exactly once per invocation), once per scripted round,
with the module's template-fetching helper and project-creation helper
mocked out. Across the eight rounds, the test varies the `--starter`,
`--tools`, `--example`, `--checkout` and `--directory` inputs so that the
target's conditional branches are taken in different combinations: some
rounds select the PySpark tooling branch, some select the example-pipeline
branch (without PySpark), some fall through to the default branch, and only
some rounds pass a truthy `directory` argument.

Task: report ALL unique observed def-use pairs, over ALL eight invocations
of `kedro.framework.cli.starters._make_cookiecutter_args_and_fetch_template`
during this test run, for exactly these eight local variables of the target
function: `config`, `checkout`, `directory`, `template_path`,
`cookiecutter_args`, `tools`, `example_pipeline`, `starter_path`.

Definitions and conventions:

- Line numbers are absolute, 1-based, in the file
  `kedro/framework/cli/starters.py` as it exists on disk in this repository.
- A "def" of a tracked variable is a binding of that bare name: a simple
  assignment to the name (e.g. `x = ...`), or a parameter binding. The four
  parameters count as defined at the line of the function's `def` statement,
  and that def is in effect from the moment the invocation begins, before
  any line of the body executes.
- A "use" of a tracked variable is any read of the name: any occurrence of
  the bare name in load position, including as the base object of a
  subscript or attribute access.
- Subscript or attribute stores such as `d[key] = value` do NOT redefine the
  base name `d` (they mutate the object it refers to); the occurrence of `d`
  in such a statement is a use of `d` (and any tracked names among the
  subscript/key/value expressions are uses as well).
- Augmented assignment (`x += 1`) reads then writes: it counts BOTH as a use
  of the previously reaching def AND as a new def of `x`, both on that line.
  (The target body contains no augmented assignment; the rule is stated for
  completeness.)
- A `for` loop header (`for x in ...:`) would redefine `x` on the header
  line once per iteration. (The target body contains no loops; the rule is
  stated for completeness.)
- Only the eight variables enumerated above are tracked. Any other local
  names, and any comprehension-local variables, are not tracked. (The target
  body contains no comprehensions.)
- A use or def is attributed to the physical line on which the variable
  reference textually appears, even when the containing statement spans
  several physical lines: for example, a name appearing on a continuation
  line of a multi-line call or multi-line dict display is attributed to that
  continuation line, not to the line where the statement begins.
- A pair {variable, def_line, use_line} is OBSERVED if, during some
  invocation of the target in this test run, the line use_line actually
  executes (fires an executed-line event, equivalent to a `line` event of
  `sys.settrace`, for the target function's own frame) and at that moment
  the reaching def of `variable` is def_line — i.e. def_line is the most
  recent def of that variable executed earlier within the SAME invocation
  (parameter bindings at the `def` line count as executed at invocation
  start), with no other def of that variable executed in between.
- Only the target function's own frame counts. Functions the target calls
  (for example the same-module helper it calls to resolve the checkout
  branch) run in separate frames; their internal lines contribute nothing.
  However, the target's own lines performing such a call (including the
  lines holding the argument expressions) DO count normally. The line
  containing the target's `return` statement also counts: it is a use of
  every tracked variable read by the return expression.
- Aggregation and deduplication: collect the observed pairs from all eight
  invocations into one set; pairs that are observed multiple times (within
  one invocation or across invocations) are reported only once.
- Invocation counting (for reference): one invocation is one entry into the
  target function during the test run, counted 1-based in chronological
  order of function entry; this test run produces exactly eight invocations,
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
    """Return (def_line, param_names, uses, defs) for the target function.

    uses/defs map physical line number -> set of tracked variable names.
    """
    try:
        with open(source_path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=source_path)
    except OSError as exc:
        fail(f"could not read target source: {exc}")

    funcdef = None
    for node in tree.body:
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
        "question_kind": "S4_DataFlow",
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
