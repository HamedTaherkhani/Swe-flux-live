"""Parse the sys.settrace log into oracle.json for instance
ipython_resolve_project_path_m1_cfg (M1_IntraProceduralCFG).

The answer is `covered_lines`: the sorted, deduplicated list of physical
source lines of kedro.ipython._resolve_project_path covered during the whole
test, under the statement-based coverage convention stated in the question:

- a statement's span is node.lineno..node.end_lineno (Python `ast`);
- a statement's "own lines" are its span minus the spans of statements
  nested directly inside it;
- a statement counts as executed iff at least one executed line event of the
  target's own frame falls on one of its own lines;
- a physical body line is covered iff it is an own line of an executed
  statement;
- the `def` statement counts as executed when the function was invoked at
  least once; its own lines are the signature lines (from the `def` line
  through the line before the first body statement).
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/ipython/__init__.py"
TARGET_FUNC = "kedro.ipython._resolve_project_path"
TARGET_FUNC_NAME = "_resolve_project_path"

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/ipython_resolve_project_path_m1_cfg/files/testcase.py::TestResolveProjectPathCfgRuntime::test_traced_run`
is executed, the function `kedro.ipython._resolve_project_path` (defined in
the repository file `kedro/ipython/__init__.py`) is invoked several times,
always indirectly: the test only calls `kedro.ipython.reload_kedro` and the
line-magic function `kedro.ipython.magic_reload_kedro`, both of which call
`_resolve_project_path` internally (the call chains are
`magic_reload_kedro` -> `reload_kedro` -> `_resolve_project_path` and
`reload_kedro` -> `_resolve_project_path`). The invocations use different
combinations of the `path` and `local_namespace` arguments, and in some
invocations `kedro.ipython.find_kedro_project` is temporarily replaced by a
test double. The target function itself is never patched or modified; it
executes normally on every invocation.

Consider a line-level execution trace of this test run, equivalent to the
`call` and `line` events that `sys.settrace` reports for the target
function's own frames (the frames executing the code object of
`kedro.ipython._resolve_project_path`; frames of any other function,
including `reload_kedro` itself, never contribute).

Task: determine which source lines of `kedro.ipython._resolve_project_path`
are COVERED during the entire test, i.e. across the union of ALL of its
invocations, under the statement-based coverage convention defined below,
and report them in the format specified at the end. One invocation is one
entry into the function (one `call` event of its frame); since the answer is
a union over all invocations, their order and numbering do not matter.

Definitions and conventions:

- Line numbers are absolute, 1-based, physical line numbers in
  `kedro/ipython/__init__.py` as the file exists in this repository.
- An "executed line event" is one `line` event reported by the tracer for
  the target function's own frame: the interpreter beginning execution of a
  source line of that frame. `call`, `return` and `exception` events are not
  line events (note however that a line containing a `return` statement DOES
  produce an executed line event when it is reached).
- Statements are delimited using Python's `ast` module applied to the file
  exactly as it exists in the repository: a statement node's physical line
  span is `node.lineno` through `node.end_lineno`, inclusive.
- The OWN LINES of a statement are the physical lines of its span that do
  not belong to the span of any statement nested directly inside it. For
  example, for an `if`/`else` statement the own lines are the header lines
  of the `if` (including the continuation lines of a multi-line condition
  and its closing `):` line) plus the `else:` line if present, but NOT the
  lines of the statements inside its body or inside its `else` block.
- A statement counts as EXECUTED during the test if and only if at least
  one executed line event (from any invocation of the target) falls on one
  of its own lines.
- A physical line of the function body counts as COVERED if and only if it
  is one of the own lines of at least one statement that counts as executed.
  Nested statements are judged independently by the same rule, so a body
  line of an `if` is covered only if that body statement itself counts as
  executed.
- The `def` statement: entering the function produces a `call` event on the
  `def` line, not a line event. For this question the `def` statement counts
  as executed whenever the function was invoked at least once, and its own
  lines -- the physical lines of the signature, from the `def` line through
  the line immediately before the function's first body statement -- count
  as covered.
- The function's docstring never produces a line event (it is a
  compile-time constant, not executed code), so by the rules above it does
  not count as executed and none of its lines are covered.
- Worked example of the own-lines rule (generic code, unrelated to the
  target): for

      if (x
              and y):
          do(x)

  if during a run the tracer recorded a line event only on the `if (x` line,
  then the `if` statement counts as executed and both of its header lines
  are covered, while the `do(x)` line is covered only if a line event fired
  on it.

Answer format: a JSON object with exactly one key, `covered_lines`, whose
value is the list of the covered line numbers (JSON integers), sorted in
ascending order, with duplicates removed.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def direct_child_stmts(node):
    return [c for c in ast.iter_child_nodes(node) if isinstance(c, ast.stmt)]


def own_lines(node):
    end = node.end_lineno or node.lineno
    lines = set(range(node.lineno, end + 1))
    for child in direct_child_stmts(node):
        child_end = child.end_lineno or child.lineno
        lines -= set(range(child.lineno, child_end + 1))
    return lines


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

    call_count = 0
    total_line_events = 0
    line_event_lines = set()

    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_FUNC:
                continue
            event = m.group("event")
            if event == "call":
                call_count += 1
            elif event == "line":
                line_event_lines.add(int(m.group("line")))
                total_line_events += 1

    if call_count == 0:
        fail(f"no call events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")

    src_path = os.path.join(args.repo_root, TARGET_FILE_REL)
    if not os.path.isfile(src_path):
        fail(f"target source not found: {src_path}")
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=TARGET_FILE_REL)

    funcdef = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == TARGET_FUNC_NAME
        ):
            funcdef = node
            break
    if funcdef is None:
        fail(f"function {TARGET_FUNC_NAME} not found in {TARGET_FILE_REL}")

    covered = set()
    # The `def` statement counts as executed (function was invoked): its own
    # lines are the signature lines up to the first body statement.
    covered |= set(range(funcdef.lineno, funcdef.body[0].lineno))

    def visit(stmt):
        own = own_lines(stmt)
        if own & line_event_lines:
            covered.update(own)
        for child in direct_child_stmts(stmt):
            visit(child)

    for stmt in funcdef.body:
        visit(stmt)

    covered_lines = sorted(covered)
    if not covered_lines:
        fail("computed an empty covered_lines set")

    print(f"call events: {call_count}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed line-event lines: {len(line_event_lines)}")
    print(f"covered lines: {len(covered_lines)}")

    oracle_answer = {"covered_lines": covered_lines}
    template_answer = {"covered_lines": ["int"]}
    oracle = {
        "question_kind": "M1_IntraProceduralCFG",
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
