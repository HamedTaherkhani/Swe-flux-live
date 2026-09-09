"""Parse the sys.settrace log into oracle.json for instance
node_from_dict_m3_state (M3_ProgramState).

The answer is the sorted set of distinct repr strings observed for the local
variables ``result`` and ``keys`` of
``kedro.pipeline.node.Node._outputs_to_dictionary._from_dict`` across ALL of
its invocations during the traced test run.  The tracer logs, per frame, the
locals that changed since the previous event (plus the full locals snapshot
on ``return``), so every value either variable takes surfaces at least once;
duplicates are removed by collecting into a set.  Values are already repr
strings in the log and are used verbatim.
"""

import argparse
import ast
import json
import os
import re
import sys

# The tracer falls back to ``code.co_name`` on Python < 3.11, so nested
# functions appear as ``<module>.<co_name>`` in the log.
TARGET_FUNC_QUALNAME = "kedro.pipeline.node._from_dict"
TRACKED_VARS = ("keys", "result")

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/node_from_dict_m3_state/files/testcase.py::TestNodeFromDictState::test_from_dict_state`
is executed, it repeatedly calls `Node.run({})` on two
`kedro.pipeline.node.Node` objects whose declared outputs are dicts (one node
maps three function-output keys to three dataset names, the other maps two),
with the shared node function returning programmatically generated payloads in
a fixed seeded order. Two of the runs intentionally fail inside output
translation (one run's function returns a list instead of a dict; another
returns a dict whose keys do not match the declared keys), and the test catches
the resulting `ValueError`s. Every `Node.run` call reaches the nested helper
function `kedro.pipeline.node.Node._outputs_to_dictionary._from_dict` (defined
in the repository file `kedro/pipeline/node.py`, lines 499-527) through the
chain `Node.run` -> `Node._run_with_no_inputs` ->
`Node._outputs_to_dictionary` -> `_from_dict`; the two failing runs reach it as
well and raise inside it.

An "invocation" means one call of `_from_dict` during this test run;
invocations are counted 1-based in chronological order and ALL invocations are
in scope, including the two that terminate by raising `ValueError`.

During every invocation, observe the two local variables `result` and `keys` of
the `_from_dict` frame. Record every distinct value each variable holds from
the moment it is first assigned until the frame exits (whether by returning or
by raising): concretely, `result` is first bound to the node function's raw
return value and, on invocations that reach the end, is later rebound to the
tuple of output values gathered in declared-key order, while `keys` is bound
once per invocation to the list of the node's declared function-output keys.
If a variable is reassigned the identical value more than once, only the
distinct values matter.

Serialize every observed value with Python's `repr()` applied to the whole
object: dicts render with single quotes in insertion order (example format:
`{'x': 1, 'y': 2}`), tuples render like `(3, 4)`, and lists render like
`[5, 6]`. Collect the distinct repr strings observed for `result` and `keys`
COMBINED into one set, across all invocations and all observation points,
removing duplicates.

Report the answer as a JSON object with a single key `unique_values` whose
value is a list containing each distinct repr string exactly once, sorted in
ascending lexicographic order under plain Python string comparison (i.e. the
order produced by `sorted()` on the strings, which is Unicode code-point
order; for example `(9, 1)` sorts before `[9, 1]`, which sorts before
`{'a': 9}`)."""


def parse_events(trace_path):
    events = []
    with open(trace_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            m = LINE_RE.match(line)
            if not m:
                continue
            if m.group("func") != TARGET_FUNC_QUALNAME:
                continue
            _sep, _eq, locals_blob = line.rpartition(" locals=")
            if not _sep:
                continue
            try:
                locals_dict = ast.literal_eval(locals_blob.strip())
            except (SyntaxError, ValueError):
                continue
            events.append(
                {
                    "line": int(m.group("line")),
                    "event": m.group("event"),
                    "locals": locals_dict,
                }
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
            f"{TARGET_FUNC_QUALNAME} in {args.trace_log}"
        )

    n_calls = sum(1 for e in events if e["event"] == "call")
    if n_calls == 0:
        sys.exit("FATAL: no call events for target function; trace unusable")

    unique = set()
    for e in events:
        for var in TRACKED_VARS:
            value = e["locals"].get(var)
            if isinstance(value, str):
                unique.add(value)

    if not unique:
        sys.exit(
            "FATAL: no observations of tracked variables "
            f"{TRACKED_VARS} in target frame events"
        )

    answer = sorted(unique)

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": answer},
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"events={len(events)} calls={n_calls} unique_values={len(answer)}")


if __name__ == "__main__":
    main()
