#!/usr/bin/env python
"""Parse the tracer log into oracle.json for backends_convert_arguments_s3_state.

The tracer logs, for every event of the target frame, only the locals whose
repr changed since the previous event of the same frame (all locals on `call`
and `return`). A `line` event is emitted *before* its line executes, so the
locals recorded there are the state the line observes. We rebuild the full
local state per invocation by accumulating these diffs.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_QUALNAME = "networkx.utils.backends._dispatchable._convert_arguments"
TARGET_FILE = "networkx/utils/backends.py"
OBS_LINE = 1342
OBS_K = 29
VARIABLES = [
    "gname",
    "edge_attrs",
    "node_attrs",
    "preserve_edge_attrs",
    "preserve_node_attrs",
    "preserve_graph_attrs",
    "edges",
    "nodes",
    "preserve_edges",
    "preserve_nodes",
    "preserve_graph",
]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) "
    r"(?:retval=.*? |exc=.*? )?locals=(?P<locals>\{.*\})$"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_events(path):
    p = Path(path)
    if not p.is_file():
        fail(f"trace log not found: {path}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {path}")
    events = []
    for raw in text.splitlines():
        if "[TRACE]" in raw:
            continue
        m = LINE_RE.match(raw)
        if not m or m["func"] != TARGET_QUALNAME:
            continue
        if not m["file"].replace("\\", "/").endswith(TARGET_FILE):
            continue
        events.append(
            (int(m["lineno"]), m["event"], ast.literal_eval(m["locals"]))
        )
    if not events:
        fail(f"no events for {TARGET_QUALNAME} in {path}")
    return events


def observations(events):
    """Yield (invocation_index, full_locals) at each line event for OBS_LINE."""
    state = None
    inv = 0
    for lineno, event, loc in events:
        if event == "call":
            inv += 1
            state = dict(loc)
            continue
        if state is None:
            fail("event before first call event")
        state.update(loc)
        if event == "line" and lineno == OBS_LINE:
            yield inv, dict(state)
        if event == "return":
            state = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    events = parse_events(args.trace_log)
    n_lines = sum(1 for e in events if e[1] == "line")
    if n_lines == 0:
        fail("no line events for target")
    obs = list(observations(events))
    if args.debug:
        for i, (inv, st) in enumerate(obs, 1):
            print(i, inv, {v: st.get(v) for v in VARIABLES})
    if len(obs) < OBS_K:
        fail(f"line {OBS_LINE} executed only {len(obs)} times (< {OBS_K})")
    _, state = obs[OBS_K - 1]
    observed = []
    for var in VARIABLES:
        if var not in state:
            fail(f"variable {var!r} not bound at observation point")
        observed.append({"value": state[var], "variable": var})

    question = (
        "Run the pytest test "
        "`networkx_qa/backends_convert_arguments_s3_state/files/testcase.py::"
        "TestLoopbackDispatchBatch::test_batch_of_dispatched_calls` (the only test "
        "method in class `TestLoopbackDispatchBatch` of file "
        "`networkx_qa/backends_convert_arguments_s3_state/files/testcase.py`). "
        "Consider the method `_dispatchable._convert_arguments` "
        f"(`{TARGET_QUALNAME}`) defined in `{TARGET_FILE}`. Over the whole test run "
        "(every invocation of that method, in chronological order, regardless of "
        "which public function or which `backend` led to it), count the executions "
        f"of line {OBS_LINE} of `{TARGET_FILE}` (1-based absolute line number in the "
        "file as it exists in the repository; it is the line "
        "`if getattr(graph, \"__networkx_backend__\", \"networkx\") != backend_name:` "
        "inside the `for gname in self.graphs:` loop). Every time that line is "
        "reached counts once, whatever the outcome of its condition. "
        f"At the moment line {OBS_LINE} executes for the {OBS_K}-th time during the "
        "test run (1-based count over the whole run), report the values of the "
        "following local variables of that `_convert_arguments` frame, in exactly "
        "this order: "
        + ", ".join(f"`{v}`" for v in VARIABLES)
        + ". Line "
        f"{OBS_LINE} assigns no local variable, so the values are the same just "
        "before and just after it executes. Each `value` is the Python `repr()` of "
        "the variable's current value, given as a JSON string: strings keep their "
        "quotes (e.g. `'abc'`), `None`/`True`/`False` use Python spelling, floats "
        "use Python repr (e.g. `0.5`, `nan`), and dicts/sets are the "
        "`repr` of the whole container in its actual (insertion/iteration) order, "
        "e.g. `{'x': 1}`. Answer as `{\"observed_state\": [{\"value\": ..., "
        "\"variable\": ...}, ...]}` with one entry per variable, listed in the order "
        "given above, `variable` being the bare local variable name."
    )

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": observed},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))
    print(f"target line events: {n_lines}; line {OBS_LINE} executions: {len(obs)}")


if __name__ == "__main__":
    main()
