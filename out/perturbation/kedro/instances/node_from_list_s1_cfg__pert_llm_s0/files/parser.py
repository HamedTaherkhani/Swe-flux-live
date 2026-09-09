"""Parse the sys.settrace log into oracle.json for instance
node_from_list_s1_cfg (S1_IntraProceduralCFG).

The answer is the exact ordered sequence of executed ``line`` events inside
``kedro.pipeline.node.Node._outputs_to_dictionary._from_list`` for its 13th
invocation during the traced test run (invocations are delimited by ``call``
events and counted 1-based in chronological order).  On CPython 3.9 the
tracer identifies frames via ``code.co_name``, so the nested helper appears
in the log as ``kedro.pipeline.node._from_list``; that same string is the
``func`` convention stated in the question.
"""

import argparse
import json
import os
import re
import sys

# The tracer falls back to ``code.co_name`` on Python < 3.11, so nested
# functions appear as ``<module>.<co_name>`` in the log.
TARGET_FUNC_LOG_NAME = "kedro.pipeline.node._from_list"
REL_FILE = "kedro/pipeline/node.py"
INVOCATION_INDEX = 13  # 1-based, by chronological order of call events
EXPECTED_INVOCATIONS = 21
MIN_PATH_EVENTS = 10

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/node_from_list_s1_cfg/files/testcase.py::TestNodeFromListCfg::test_from_list_cfg_paths`
is executed, it repeatedly calls `Node.run({})` on two
`kedro.pipeline.node.Node` objects whose declared `outputs` are lists of
dataset names (one node declares three outputs, the other declares two).
The shared node function returns programmatically generated payloads in a
fixed seeded order: plain lists of integers for some runs, generators
yielding tuples of integers for others. Four of the runs intentionally fail
inside output translation (in one run the function returns a plain integer;
in one run a list whose length does not match the declaration; in one run a
generator whose first yielded item is not a list or tuple; and in one run a
generator whose first yielded tuple has the wrong length), and the test
catches the resulting `ValueError`s.

Every `Node.run` call reaches the nested helper function `_from_list`,
defined inside `Node._outputs_to_dictionary` in the repository file
`kedro/pipeline/node.py` (its fully qualified name is
`kedro.pipeline.node.Node._outputs_to_dictionary._from_list`), through the
chain `Node.run` -> `Node._run_with_no_inputs` ->
`Node._outputs_to_dictionary` -> `_from_list`. In total, `_from_list` is
invoked 21 times during this test.

An "invocation" means one call of `_from_list` during this test run;
invocations are counted 1-based in chronological order of the calls, and ALL
21 invocations are in scope, including the four that terminate by raising
`ValueError`.

Consider the 13th invocation (this is the run in which the node function
returns a generator whose first yielded tuple has a length that does not
match the number of declared outputs, so the invocation ends by raising
`ValueError`). Report the exact ordered sequence of executed source lines
inside the body of `_from_list` during that single invocation, as a list of
executed-line events under the rules below.

Line-event semantics (the interpreter is CPython 3.9):
- The sequence contains one element per executed-line step of the
  `_from_list` frame, in chronological order, from the first executable
  statement of the body up to and including the last line the frame
  executes before it exits (whether by returning or by raising).
- The `def _from_list():` line does NOT appear in the sequence: entering
  the function is a call step, not an executed-line step, and no element is
  recorded for the `def` line (nor for any decorator or docstring line).
- Each element records the physical, 1-based line number in
  `kedro/pipeline/node.py` (the file as it exists on disk in this
  repository) at which the frame was executing. A single-line statement
  contributes exactly one element carrying its own line number.
- Multi-line statements do NOT collapse to a single element at the
  statement's first line: every physical line to which the CPython 3.9
  compiler attributes executed bytecode contributes its own element when
  reached. In particular, this function's `raise ValueError(...)`
  statements build their message from an f-string that spans several
  physical lines, and evaluating such a message emits executed-line steps
  for the physical lines holding the replacement-field pieces, possibly
  revisiting an earlier physical line of the same statement between pieces.
  Consequently the same line number may appear multiple times in the
  sequence; keep every occurrence in order and do NOT deduplicate. The only
  reliable way to obtain these per-line steps is to instrument the run
  yourself (for example with your own `sys.settrace` line tracer) rather
  than to guess them from a static reading of the source.

Report the answer as a JSON object with a single key `executed_path` whose
value is the ordered list of executed-line events for the 13th invocation.
Each element is an object with exactly these keys:
- `file`: the string `"kedro/pipeline/node.py"` (the repo-relative path) in
  every element;
- `func`: the string `"kedro.pipeline.node._from_list"` in every element —
  note this convention uses the module dotted path plus the function's bare
  name, WITHOUT the enclosing `Node._outputs_to_dictionary` qualifiers (for
  example, the sibling helper `_from_dict` in the same file would be
  reported as `kedro.pipeline.node._from_dict`);
- `line`: the 1-based physical line number as an integer.

No elements are added, removed, reordered, or deduplicated beyond these
rules."""


def parse_events(trace_path):
    events = []
    with open(trace_path, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_FUNC_LOG_NAME:
                continue
            if REL_FILE not in m.group("file").replace("\\", "/"):
                continue
            events.append(
                {"line": int(m.group("line")), "event": m.group("event")}
            )
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        sys.exit(f"FATAL: trace log missing: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        sys.exit(f"FATAL: trace log is empty: {args.trace_log}")

    events = parse_events(args.trace_log)
    if not events:
        sys.exit(
            f"FATAL: zero trace events for target function "
            f"{TARGET_FUNC_LOG_NAME} in {args.trace_log}"
        )

    invocations = []
    current = None
    for e in events:
        if e["event"] == "call":
            current = []
            invocations.append(current)
        elif e["event"] == "line" and current is not None:
            current.append(e["line"])

    if not invocations:
        sys.exit("FATAL: no call events for target function; trace unusable")
    if len(invocations) != EXPECTED_INVOCATIONS:
        sys.exit(
            f"FATAL: expected {EXPECTED_INVOCATIONS} invocations of "
            f"{TARGET_FUNC_LOG_NAME}, found {len(invocations)}"
        )
    if len(invocations) < INVOCATION_INDEX:
        sys.exit(
            f"FATAL: invocation {INVOCATION_INDEX} not present; only "
            f"{len(invocations)} invocations traced"
        )

    path = invocations[INVOCATION_INDEX - 1]
    if len(path) < MIN_PATH_EVENTS:
        sys.exit(
            f"FATAL: invocation {INVOCATION_INDEX} produced only "
            f"{len(path)} line events (< {MIN_PATH_EVENTS}); "
            "answer would be trivial"
        )

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {
            "executed_path": [
                {"file": REL_FILE, "func": TARGET_FUNC_LOG_NAME, "line": ln}
                for ln in path
            ]
        },
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(
        f"events={len(events)} invocations={len(invocations)} "
        f"path_len={len(path)} path={path}"
    )


if __name__ == "__main__":
    main()
