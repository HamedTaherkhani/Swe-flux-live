#!/usr/bin/env python
"""Trace -> oracle.json for utils_get_value_s2_loops (S2_Loops)."""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/utils.py"
TARGET_QUAL = "marshmallow.utils.get_value"
TEST_PATH = "marshmallow_qa/utils_get_value_s2_loops/files/testcase.py"
TEST_CLASS = "GetValueWalkTest"
TEST_METHOD = "test_dotted_walk_over_box_graph"
NTH_ITERATION = 38
VARIABLE = "obj"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)?(?: exc=.*?)? locals=(?P<locals>\{.*\})$"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_loop(source_path):
    """Return (header_line, body_first_line) of the for-loop inside get_value."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == "get_value":
            loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
            if len(loops) != 1:
                fail(f"expected exactly one for-loop in get_value, found {len(loops)}")
            return loops[0].lineno, loops[0].body[0].lineno
    fail("could not locate get_value in target source")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    src = Path(__file__).resolve().parents[3] / TARGET_REL
    if not src.is_file():
        src = Path.cwd() / TARGET_REL
    header, body_first = find_loop(src)

    invocations = []  # per invocation: list of obj reprs observed at each body-first-line event
    state = {}
    target_events = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_REL) or m.group("func") != TARGET_QUAL:
            continue
        target_events += 1
        ev = m.group("event")
        try:
            changed = ast.literal_eval(m.group("locals"))
        except Exception as e:
            fail(f"cannot parse locals in trace line: {raw!r} ({e})")
        if ev == "call":
            state = dict(changed)
            invocations.append([])
            continue
        if not invocations:
            fail("line event before any call event")
        state.update(changed)
        if ev == "line" and int(m.group("line")) == body_first:
            if VARIABLE not in state:
                fail(f"variable {VARIABLE!r} not in locals at line {body_first}")
            invocations[-1].append(state[VARIABLE])

    if target_events == 0 or not invocations:
        fail("no events for target function in trace")
    if len(invocations) != 1:
        fail(f"expected exactly one invocation of get_value, got {len(invocations)}")
    seen = invocations[0]
    if len(seen) < NTH_ITERATION:
        fail(f"loop ran only {len(seen)} iterations, need {NTH_ITERATION}")
    value = seen[NTH_ITERATION - 1]
    if value.endswith("..."):
        fail("repr was truncated by tracer")

    question = (
        f"Run the pytest test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` "
        f"(test class `{TEST_CLASS}`, single test method `{TEST_METHOD}`). During this test the "
        f"function `marshmallow.utils.get_value` defined in `{TARGET_REL}` is invoked exactly once "
        f"(invocation 1 = the first and only call in chronological order). Consider the `for` loop "
        f"whose header is at line {header} of `{TARGET_REL}` (absolute, 1-based line numbers in the "
        f"file as it exists in the repository); its body is the single statement at line {body_first}. "
        f"Iterations are counted 1-based: iteration N is the Nth time line {body_first} begins "
        f"executing during that invocation. What is the value of the local variable `{VARIABLE}` "
        f"at the moment line {body_first} begins executing in iteration {NTH_ITERATION}, i.e. BEFORE "
        f"that iteration's assignment to `{VARIABLE}` runs (equivalently, the value `{VARIABLE}` holds "
        f"after iteration {NTH_ITERATION - 1} finished)? "
        f"Answer as a JSON object with exactly the keys `nth_iteration` (int, the iteration number "
        f"asked about, i.e. {NTH_ITERATION}), `variable` (str, the bare variable name, i.e. "
        f"\"{VARIABLE}\"), and `value` (str, the Python `repr()` of the object exactly as produced by "
        f"its class's `__repr__`, e.g. a Box tagged 'x9' would be written as the string "
        f"\"Box('x9')\" with single quotes inside)."
    )

    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"nth_iteration": "int", "value": "str", "variable": "str"},
        "oracle_answer": {"nth_iteration": NTH_ITERATION, "value": value, "variable": VARIABLE},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
