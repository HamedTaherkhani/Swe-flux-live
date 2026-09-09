"""Parse the sys.settrace log into oracle.json for instance
utils_remove_nested_section_s2_loops (S2_Loops).

The answer is the iteration count of the `for` loop whose header is at
line 68 of kedro/templates/project/hooks/utils.py during the
TARGET_INVOCATION-th invocation (1-based, chronological order of `call`
events) of kedro.templates.project.hooks.utils._remove_nested_section.
One iteration = one execution of the first line of that loop's body; the
body's first line is resolved from the repository source via `ast`.
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/templates/project/hooks/utils.py"
TARGET_FUNC = "kedro.templates.project.hooks.utils._remove_nested_section"
TARGET_FUNC_NAME = "_remove_nested_section"
TARGET_INVOCATION = 3
LOOP_HEADER_LINE = 68

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/utils_remove_nested_section_s2_loops/files/testcase.py::TestTomlSectionCleanupLoops::test_traced_run`
is executed, the function
`kedro.templates.project.hooks.utils._remove_nested_section` (defined in
the repository file `kedro/templates/project/hooks/utils.py`) is invoked
multiple times indirectly: the test builds one nested TOML document
programmatically, writes it to a temporary file, and calls the same-module
helper `_remove_from_toml` once with an ordered list of dotted section
keys; `_remove_from_toml` parses the file and invokes
`_remove_nested_section` once per section key, in list order. Earlier
removals change what later removals cascade through, because they share
ancestor sections.

Invocation counting: invocations of
`kedro.templates.project.hooks.utils._remove_nested_section` are counted
1-based, in chronological order of function entry, where one invocation is
one entry into the function (one `call` event as seen by a line-level
execution tracer) during the test run.

Focus on the `for` loop whose header is at line 68 of
`kedro/templates/project/hooks/utils.py` (the loop
`for key in reversed(keys[:-1]):`, line numbers being absolute and 1-based
in the file as it exists on disk in this repository). Define one iteration
of this loop as one execution of the first line of the loop body (i.e. the
first physical line nested under the loop header). An iteration still
counts if it ends by executing the loop's `break` statement. If the loop
body never executes, the iteration count is 0. The nested inner `for` loop
inside this loop's body is irrelevant: only executions of the outer loop
body's first line are counted.

Task: report the exact number of iterations of the loop at line 68 during
the 3rd invocation of
`kedro.templates.project.hooks.utils._remove_nested_section` in this test
run.

Answer format: a JSON object with exactly one key, `loop_iteration_count`,
whose value is a single integer (a JSON number, not a string).
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
            if event == "call":
                if current is not None:
                    invocations.append(current)
                current = []
            elif event == "line":
                if current is None:
                    fail("line event encountered before any call event")
                lineno = int(m.group("line"))
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
    if len(invocations) < TARGET_INVOCATION:
        fail(
            f"only {len(invocations)} invocation(s) traced; "
            f"need invocation {TARGET_INVOCATION}"
        )

    path_lines = invocations[TARGET_INVOCATION - 1]
    iteration_count = sum(1 for ln in path_lines if ln == body_first_line)
    if iteration_count == 0:
        fail(
            f"loop body first line {body_first_line} never executed in "
            f"invocation {TARGET_INVOCATION}"
        )

    print(f"loop header line: {LOOP_HEADER_LINE}")
    print(f"loop body first line: {body_first_line}")
    print(f"invocations traced: {len(invocations)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"invocation {TARGET_INVOCATION} executed lines: {len(path_lines)}")
    print(f"loop iteration count: {iteration_count}")

    oracle_answer = {"loop_iteration_count": iteration_count}
    template_answer = {"loop_iteration_count": "int"}
    oracle = {
        "question_kind": "S2_Loops",
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
