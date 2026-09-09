"""Parse the sys.settrace log into oracle.json for instance
runner_find_all_nodes_for_resumed_pipeline_m2_loops (M2_Loops).

The answer is the maximum and minimum, across all invocations of
kedro.runner.runner._find_all_nodes_for_resumed_pipeline during the test,
of the per-invocation iteration count of the `for` loop whose header is at
line 465 of kedro/runner/runner.py.  One iteration = one execution of the
first line of that loop's body; the body's first line is resolved from the
repository source via `ast`.  Per-invocation counts accumulate executions
over the whole invocation (all passes of the enclosing `while` loop).
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/runner/runner.py"
TARGET_FUNC = "kedro.runner.runner._find_all_nodes_for_resumed_pipeline"
TARGET_FUNC_NAME = "_find_all_nodes_for_resumed_pipeline"
LOOP_HEADER_LINE = 465

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/runner_find_all_nodes_for_resumed_pipeline_m2_loops/files/testcase.py::TestResumePipelineLoops::test_traced_run`
is executed, the function
`kedro.runner.runner._find_all_nodes_for_resumed_pipeline` (defined in the
repository file `kedro/runner/runner.py`) is invoked multiple times
indirectly: the test programmatically builds a sequence of layered
`Pipeline` objects (varying layer count, layer width, inter-layer fan-in,
which intermediate datasets are registered as persisted in the catalog, and
which nodes are reported as already done) and, for each scenario, calls
`AbstractRunner._suggest_resume_scenario` on a `SequentialRunner` instance
exactly once. Each such call leads (through the same-module helper
`_find_nodes_to_resume_from`) to exactly one invocation of
`kedro.runner.runner._find_all_nodes_for_resumed_pipeline`, so the number of
invocations equals the number of scenarios the test exercises.

Invocation counting: one invocation is one entry into the function (one
`call` event as seen by a line-level execution tracer); invocations are
numbered 1-based in chronological order of function entry during the test
run.

Loop of interest: the `for` loop whose header is at line 465 of
`kedro/runner/runner.py` (the loop
`for node in _enumerate_nodes_with_outputs(pipeline, non_persistent_inputs):`),
which is nested inside the `while queue:` loop at line 460. Line numbers are
absolute and 1-based in the file as it exists on disk in this repository.
Define one iteration of this `for` loop as one execution of the first
physical line of its body (line 466, `if node in visited:`) within the
target function's own frame. An iteration still counts when it ends by
executing the loop's `continue` statement. If the `for` loop body never
executes during a pass of the enclosing `while` loop, that pass contributes
0 iterations. Lines executed inside helper functions called by the target
(such as `_enumerate_non_persistent_inputs` or
`_enumerate_nodes_with_outputs`) run in separate frames and never count.

Per-invocation iteration count: for each invocation of
`kedro.runner.runner._find_all_nodes_for_resumed_pipeline`, count the total
number of iterations of the `for` loop at line 465 accumulated over the
entire invocation, i.e. summed over all passes of the enclosing `while`
loop during that invocation.

Task: report the maximum and the minimum of the per-invocation iteration
counts, taken over ALL invocations of
`kedro.runner.runner._find_all_nodes_for_resumed_pipeline` during this test
run. Every invocation is included, even when several invocations share the
same count (the maximum and minimum are taken over the multiset of
per-invocation counts, so duplicates do not collapse).

Answer format: a JSON object with exactly two keys:
- `max_iterations`: the largest per-invocation iteration count, a JSON
  integer (a JSON number, not a string);
- `min_iterations`: the smallest per-invocation iteration count, a JSON
  integer (a JSON number, not a string).
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def loop_body_first_line(repo_root):
    src_path = os.path.join(repo_root, TARGET_FILE_REL)
    if not os.path.isfile(src_path):
        fail(f"target source not found: {src_path}")
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src_path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == TARGET_FUNC_NAME
        ):
            for sub in ast.walk(node):
                if isinstance(sub, ast.For) and sub.lineno == LOOP_HEADER_LINE:
                    if not sub.body:
                        fail(f"loop at line {LOOP_HEADER_LINE} has empty body")
                    return sub.body[0].lineno
    fail(
        f"could not locate for-loop at line {LOOP_HEADER_LINE} "
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

    body_first_line = loop_body_first_line(args.repo_root)

    per_invocation_counts = []
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
            if event == "call":
                if current is not None:
                    fail("call event encountered before previous invocation closed")
                current = 0
            elif event == "line":
                if current is None:
                    fail("line event encountered before any call event")
                lineno = int(m.group("line"))
                if lineno == body_first_line:
                    current += 1
                total_line_events += 1
                distinct_lines.add(lineno)
            elif event in ("return", "exception"):
                if current is not None:
                    per_invocation_counts.append(current)
                    current = None
    if current is not None:
        fail("trace ended with an unterminated invocation")

    if not per_invocation_counts:
        fail(f"no events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")
    if sum(per_invocation_counts) == 0:
        fail(
            f"loop body first line {body_first_line} never executed in any "
            f"of the {len(per_invocation_counts)} invocation(s)"
        )

    max_iterations = max(per_invocation_counts)
    min_iterations = min(per_invocation_counts)

    print(f"loop header line: {LOOP_HEADER_LINE}")
    print(f"loop body first line: {body_first_line}")
    print(f"invocations traced: {len(per_invocation_counts)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"per-invocation iteration counts: {sorted(per_invocation_counts)}")
    print(f"max iterations: {max_iterations}")
    print(f"min iterations: {min_iterations}")

    oracle_answer = {
        "max_iterations": max_iterations,
        "min_iterations": min_iterations,
    }
    template_answer = {"max_iterations": "int", "min_iterations": "int"}
    oracle = {
        "question_kind": "M2_Loops",
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
