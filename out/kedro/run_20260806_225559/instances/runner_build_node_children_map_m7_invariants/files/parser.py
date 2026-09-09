"""Parse the sys.settrace log into oracle.json for instance
runner_build_node_children_map_m7_invariants (M7_Invariants).

The answer checks the candidate invariant `input_dataset in output_to_node`
at every execution of the `if` statement inside the second loop nest of
kedro.runner.runner._build_node_children_map during the test run.  One
observation is one execution of that `if` line in the target function's own
frame; the predicate holds exactly when the `if` body executes next.  The
`if` line and the first line of its body are resolved from the repository
source via `ast` (matched by the comparison's operand names, not by
hardcoded line numbers).
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/runner/runner.py"
TARGET_FUNC = "kedro.runner.runner._build_node_children_map"
TARGET_FUNC_NAME = "_build_node_children_map"
TEST_ID = (
    "kedro_qa/runner_build_node_children_map_m7_invariants/files/"
    "testcase.py::TestChildrenMapInvariants::test_traced_run"
)

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/runner_build_node_children_map_m7_invariants/files/testcase.py::TestChildrenMapInvariants::test_traced_run`
is executed, the function
`kedro.runner.runner._build_node_children_map` (defined in the repository
file `kedro/runner/runner.py`) is invoked multiple times INDIRECTLY: the
test programmatically builds a sequence of layered `Pipeline` objects
(varying layer count, layer width, inter-layer fan-in, how many first-layer
nodes take a second external input, and whether the first layer consists of
source nodes with no inputs) and, for each scenario, calls
`SequentialRunner.run(pipeline, catalog, only_missing_outputs=True)`
exactly once. Each such run performs exactly one call into
`kedro.runner.runner._build_node_children_map` (through
`AbstractRunner._filter_pipeline_for_missing_outputs`), with the full
unfiltered pipeline of that scenario as its `pipeline` argument, so the
number of invocations equals the number of scenarios the test exercises.

Invocation counting: one invocation is one entry into the function during
the test run (one function-entry event as seen by a line-level execution
tracer); invocations are ordered chronologically by function entry. All
quantities below are accumulated over ALL invocations combined; nothing is
reported per invocation.

Observation point and iteration definition: inside the target function, the
second loop nest (`for node in pipeline.nodes:` / `for input_dataset in
node.inputs:`) contains the statement `if input_dataset in output_to_node:`.
One "iteration" (one observation) is one execution of that `if` line within
the target function's OWN frame. Line numbers are absolute and 1-based in
the file as it exists on disk in this repository. Only the target
function's own frame counts: the dict comprehension that initializes
`node_children` runs in a separate comprehension frame and must NOT be
counted, and no helper functions are called from within this loop nest.
Note the `if` line executes once per visited element of each node's input
list, i.e. once per (node, input-dataset-name) pair, including pairs whose
dataset name is not produced by any node of the pipeline.

Candidate predicate (verbatim):
    input_dataset in output_to_node
evaluated on the local variables of the target function's frame at the
moment the `if` line executes. "Held" at an observation means the predicate
evaluates to True, i.e. the `if` body (`parent = output_to_node[...]` and
the following `node_children[parent].add(node)`) is entered; "violated"
means it evaluates to a negative result and the `if` body is skipped for
that pair.

Zero-observation rule: if the `if` line never executes during the entire
test run, the invariant is not evaluable; in that case report
`is_invariant_always_held` as the negative JSON boolean and both integer
fields as 0. (You may assume the test does execute it many times.)

Answer format: a JSON object with EXACTLY these three keys:
- `is_invariant_always_held`: a JSON boolean (lowercase spelling, the
  literal token that Python's `json.dumps` emits for a Python bool),
  indicating whether the candidate predicate held at EVERY observation;
- `total_iterations_observed`: a JSON integer (a JSON number, not a
  string), the total number of observations across all invocations;
- `violating_iteration_count`: a JSON integer (a JSON number, not a
  string), the total number of observations at which the predicate was
  violated.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_lines(repo_root):
    """Return (if_line, body_first_line) for the `if` statement whose test is
    `input_dataset in output_to_node` inside the target function."""
    src_path = os.path.join(repo_root, TARGET_FILE_REL)
    if not os.path.isfile(src_path):
        fail(f"target source not found: {src_path}")
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src_path)

    func = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == TARGET_FUNC_NAME
        ):
            func = node
            break
    if func is None:
        fail(f"function {TARGET_FUNC_NAME} not found in {src_path}")

    def is_target_test(test):
        return (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "input_dataset"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.In)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Name)
            and test.comparators[0].id == "output_to_node"
        )

    for sub in ast.walk(func):
        if isinstance(sub, ast.If) and is_target_test(sub.test):
            if not sub.body:
                fail("target `if` statement has an empty body")
            return sub.lineno, sub.body[0].lineno
    fail(
        f"could not locate `if input_dataset in output_to_node:` "
        f"inside {TARGET_FUNC_NAME} in {src_path}"
    )


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

    if_line, body_first_line = resolve_lines(args.repo_root)

    invocations = 0
    open_invocation = False
    total_line_events = 0
    distinct_lines = set()
    observations = 0
    held = 0

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
                if open_invocation:
                    fail("call event encountered before previous invocation closed")
                invocations += 1
                open_invocation = True
            elif event == "line":
                if not open_invocation:
                    fail("line event encountered before any call event")
                total_line_events += 1
                distinct_lines.add(lineno)
                if lineno == if_line:
                    observations += 1
                elif lineno == body_first_line:
                    held += 1
            elif event in ("return", "exception"):
                if not open_invocation:
                    fail("return/exception event encountered before any call event")
                open_invocation = False
    if open_invocation:
        fail("trace ended with an unterminated invocation")

    if invocations == 0:
        fail(f"no events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")
    if observations == 0:
        fail(f"observation line {if_line} never executed")
    if held > observations:
        fail(
            f"body line {body_first_line} executed more often ({held}) "
            f"than the observation line {if_line} ({observations})"
        )

    violations = observations - held

    print(f"test id: {TEST_ID}")
    print(f"observation (if) line: {if_line}")
    print(f"body first line: {body_first_line}")
    print(f"invocations traced: {invocations}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"observations: {observations}")
    print(f"held: {held}")
    print(f"violations: {violations}")

    oracle_answer = {
        "is_invariant_always_held": violations == 0,
        "total_iterations_observed": observations,
        "violating_iteration_count": violations,
    }
    template_answer = {
        "is_invariant_always_held": "bool",
        "total_iterations_observed": "int",
        "violating_iteration_count": "int",
    }
    oracle = {
        "question_kind": "M7_Invariants",
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
