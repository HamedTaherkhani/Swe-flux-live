"""Parse the sys.settrace log into oracle.json for instance
task_run_node_sequential_m6_calls (M6_InterProceduralCFG).

The answer is the set of tracked functions (a fixed list of ten functions,
all defined in ``kedro/runner/task.py``) that are COVERED during the test
run, i.e. invoked at least once (at least one ``call`` event), regardless of
caller.  The covered set is emitted sorted in ascending ASCII lexicographic
order of the dotted qualname.

The tracer runs on Python 3.9, where code objects have no ``co_qualname``,
so trace lines identify frames as ``module.co_name`` (the class or
enclosing-function component is lost).  The parser reconstructs the
canonical dotted qualname of every traced function by walking the AST of
the target source file (taken from the absolute path in the trace itself)
and fails loudly if any traced name is ambiguous.
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/runner/task.py"
MODULE_NAME = "kedro.runner.task"
TARGET_FUNC = "kedro.runner.task.Task._run_node_sequential"

TRACKED_FUNCS = [
    "kedro.runner.task.Task.__init__",
    "kedro.runner.task.Task.__call__",
    "kedro.runner.task.Task.execute",
    "kedro.runner.task.Task._bootstrap_subprocess",
    "kedro.runner.task.Task._run_node_synchronization",
    "kedro.runner.task.Task._run_node_sequential",
    "kedro.runner.task.Task._run_node_async",
    "kedro.runner.task.Task._synchronous_dataset_load",
    "kedro.runner.task.Task._collect_inputs_from_hook",
    "kedro.runner.task.Task._call_node_run",
]
TRACKED_SET = frozenset(TRACKED_FUNCS)

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/task_run_node_sequential_m6_calls/files/testcase.py::TestSequentialRunCoverage::test_sequential_pipeline_coverage`
is executed, it programmatically builds (with a seeded random generator) a
14-node Kedro pipeline — regular nodes with one or two inputs and one or two
outputs, two streaming generator nodes (one yielding tuples, one yielding
dicts), and a final reducer node — and runs it once end to end through
`kedro.runner.sequential_runner.SequentialRunner` (constructed with its
default arguments) against a `DataCatalog` backed by `MemoryDataset`
objects, with a real pluggy hook manager carrying one registered
`before_node_run` hook implementation. Every node execution flows through
the target function `kedro.runner.task.Task._run_node_sequential` (defined
in the repository file `kedro/runner/task.py`, lines 141-190), so the target
is invoked many times during the test run.

Definitions used in this question:

- Function identity is the dotted qualname derived from the source file's
  structure: `module.Class.method` for methods and `module.function` for
  module-level functions. For example, `kedro.pipeline.node.Node.run` is the
  qualname of the method `run` of class `Node` in module
  `kedro.pipeline.node`.
- Invocation: one invocation of a function is one entry into the function
  (one function call); invocations are counted 1-based in chronological
  order of function entry during the test run. Repeated invocations of the
  same function are separate invocations. None of the tracked functions
  below is a generator function, so no generator-resumption subtleties
  arise.
- Coverage: a function is COVERED if and only if it is invoked at least once
  during the entire test run, no matter which caller invoked it (directly or
  transitively) and no matter what else is on the call stack at that moment.
  Coverage is a per-function property of the whole run: a function invoked
  many times is still reported exactly once, and a function never invoked is
  not reported at all.

The tracked set is EXACTLY these ten functions (all defined in
`kedro/runner/task.py`):

1. `kedro.runner.task.Task.__init__`
2. `kedro.runner.task.Task.__call__`
3. `kedro.runner.task.Task.execute`
4. `kedro.runner.task.Task._bootstrap_subprocess`
5. `kedro.runner.task.Task._run_node_synchronization`
6. `kedro.runner.task.Task._run_node_sequential`
7. `kedro.runner.task.Task._run_node_async`
8. `kedro.runner.task.Task._synchronous_dataset_load`
9. `kedro.runner.task.Task._collect_inputs_from_hook`
10. `kedro.runner.task.Task._call_node_run`

Note that several of these functions may legitimately not run at all during
this test; the answer must reflect what actually executes, not what a static
call-graph over-approximation suggests.

Task: report which of the ten tracked functions are COVERED (invoked at
least once) during the test run.

Answer format: a JSON object with exactly one key, `covered_functions`,
whose value is a list with exactly one object per covered tracked function.
Each object has exactly two keys: `file` (a JSON string giving the
repo-relative path of the file defining the function — for every entry in
this answer it is `kedro/runner/task.py`) and `func` (a JSON string giving
the dotted qualname of the function, in the format defined above, spelled
exactly as in the tracked-set list). The list is sorted in ascending ASCII
lexicographic order of the `func` string (underscore, code point 95, sorts
before lowercase letters; for example `m.x_a` sorts before `m.xz`). Since
every `file` value in this answer is identical, `file` never participates in
ordering. Each covered function appears exactly once — no duplicates.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def build_qualname_map(source_path: str) -> dict:
    """Map each function's co_name to its canonical dotted qualname(s),
    derived from the source file structure."""
    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    mapping: dict[str, set] = {}

    def walk(node, parts, inside_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, parts + [child.name], False)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual_parts = list(parts)
                if inside_function:
                    qual_parts.append("<locals>")
                qual_parts.append(child.name)
                mapping.setdefault(child.name, set()).add(
                    MODULE_NAME + "." + ".".join(qual_parts)
                )
                walk(child, qual_parts, True)
            else:
                walk(child, parts, inside_function)

    walk(tree, [], False)
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")

    source_path = None
    total_line_events = 0
    distinct_lines = set()
    call_events = 0
    covered_co_names = set()

    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            abs_file = m.group("file").replace("\\", "/")
            if not abs_file.endswith(TARGET_FILE_REL):
                fail(f"unexpected traced file path: {abs_file}")
            if source_path is None:
                source_path = abs_file
            func_field = m.group("func")
            if not func_field.startswith(MODULE_NAME + "."):
                fail(f"unexpected traced function name: {func_field}")
            co_name = func_field[len(MODULE_NAME) + 1:]
            if "." in co_name:
                fail(f"unexpected dotted co_name in trace: {func_field}")
            event = m.group("event")
            if event == "line":
                total_line_events += 1
                distinct_lines.add(int(m.group("line")))
            elif event == "call":
                call_events += 1
                covered_co_names.add(co_name)

    if total_line_events == 0 and call_events == 0:
        fail("no trace events for the target file")
    if source_path is None or not os.path.isfile(source_path):
        fail(f"target source file not found: {source_path}")

    qualname_map = build_qualname_map(source_path)

    def canonical(co_name: str) -> str:
        quals = qualname_map.get(co_name)
        if not quals:
            fail(f"traced function {co_name!r} not found in target source AST")
        if len(quals) > 1:
            fail(f"ambiguous co_name {co_name!r}: {sorted(quals)}")
        return next(iter(quals))

    covered = set()
    for co_name in sorted(covered_co_names):
        qual = canonical(co_name)
        if qual not in TRACKED_SET:
            fail(f"unexpected non-tracked function traced: {qual}")
        covered.add(qual)

    if TARGET_FUNC not in covered:
        fail(f"no call events for target function {TARGET_FUNC} in trace log")
    if total_line_events < 50:
        fail(f"degenerate trace: only {total_line_events} line events")
    if len(distinct_lines) < 8:
        fail(f"degenerate trace: only {len(distinct_lines)} distinct lines")
    if call_events < 15:
        fail(f"degenerate trace: only {call_events} call events")
    if len(covered) < 4:
        fail(f"degenerate trace: only {len(covered)} distinct covered functions")

    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"total call events: {call_events}")
    print(f"covered tracked functions: {len(covered)} of {len(TRACKED_FUNCS)}")

    sequence = [
        {"file": TARGET_FILE_REL, "func": qual} for qual in sorted(covered)
    ]

    oracle_answer = {"covered_functions": sequence}
    template_answer = {"covered_functions": [{"file": "str", "func": "str"}]}
    oracle = {
        "question_kind": "M6_InterProceduralCFG",
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
