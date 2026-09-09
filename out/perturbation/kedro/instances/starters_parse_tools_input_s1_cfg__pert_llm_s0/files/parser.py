"""Parse the sys.settrace log into oracle.json for instance
starters_parse_tools_input_s1_cfg (S1_IntraProceduralCFG).

The answer is the exact ordered sequence of executed line events inside
kedro.framework.cli.starters._parse_tools_input for its TARGET_INVOCATION-th
invocation (1-based, chronological order of `call` events).
"""

import argparse
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/framework/cli/starters.py"
TARGET_FUNC = "kedro.framework.cli.starters._parse_tools_input"
TARGET_INVOCATION = 4

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/starters_parse_tools_input_s1_cfg/files/testcase.py::TestParseToolsInputCfgRuntime::test_traced_run`
is executed, the function `kedro.framework.cli.starters._parse_tools_input`
(defined in the repository file `kedro/framework/cli/starters.py`) is invoked
several times indirectly, through the call chain `_get_extra_context` ->
`_fetch_validate_parse_config_from_user_prompts` ->
`_parse_tools_input`, once per scripted prompt round of the test.

Invocation counting: invocations of
`kedro.framework.cli.starters._parse_tools_input` are counted 1-based, in
chronological order of function entry, where one invocation is one entry into
the function (one `call` event as seen by a line-level execution tracer)
during the test run.

Task: report the exact ordered sequence of executed line events inside
`kedro.framework.cli.starters._parse_tools_input` during its 4th invocation.

Definitions and conventions:

- An "executed line event" is one `line` event as reported by a line-level
  execution tracer (equivalent to the `line` events of `sys.settrace`) for
  the target function's own frame: each time the interpreter begins executing
  a source line of that frame, the absolute 1-based line number in
  `kedro/framework/cli/starters.py` (as the file exists on disk in this
  repository) is recorded, in chronological order.
- Only the target function's own frame counts. The nested helper
  `_validate_range` defined inside the target runs in its own separate
  frames, so the lines of its body never appear in the sequence. However, the
  `def _validate_range(...)` statement itself is a statement of the target's
  body, and its line DOES appear once per invocation, at the moment that
  statement executes. Generator-expression frames created by the target are
  likewise separate frames and contribute nothing to the sequence.
- The target function's own `def` line and its docstring lines never produce
  line events (entering the function produces a `call` event, not a `line`
  event), so they do not appear in the sequence.
- `call`, `return`, and `exception` trace events are not part of the
  sequence. Note however that a line containing a `return` statement DOES
  produce an executed line event when it is reached, immediately before the
  function returns.
- The `for` loop header line produces one executed line event per iteration
  plus one final event when the iterator is exhausted and the loop exits.
- Every statement in the target function's body occupies a single physical
  line (the body contains no multi-line statements), so each executed line
  event corresponds to the statement on that exact line.
- No deduplication: if the same line executes repeatedly, each execution is a
  separate element of the sequence and consecutive repeats are kept.

Answer format: a JSON object with exactly one key, `executed_path`, whose
value is a list of objects in chronological execution order. Each element is
`{"file": <str>, "func": <str>, "line": <int>}` where `file` is the
repo-relative path `kedro/framework/cli/starters.py` (identical in every
element), `func` is the dotted module qualname
`kedro.framework.cli.starters._parse_tools_input` (identical in every
element), and `line` is the recorded line number (an integer).
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


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
            func = m.group("func")
            event = m.group("event")
            if func != TARGET_FUNC:
                continue
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
    if not path_lines:
        fail(f"invocation {TARGET_INVOCATION} has an empty executed path")

    print(f"invocations traced: {len(invocations)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"invocation {TARGET_INVOCATION} path length: {len(path_lines)}")

    oracle_answer = {
        "executed_path": [
            {"file": TARGET_FILE_REL, "func": TARGET_FUNC, "line": lineno}
            for lineno in path_lines
        ]
    }
    template_answer = {
        "executed_path": [{"file": "str", "func": "str", "line": "int"}]
    }
    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
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
