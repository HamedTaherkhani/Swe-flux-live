"""Harvest S3_ProgramState oracle for _get_parallel_coordinate_plot from the trace log."""

import argparse
import ast
import json
import re
import sys

TARGET_FUNC = "optuna.visualization.matplotlib._parallel_coordinate._get_parallel_coordinate_plot"
TARGET_FILE = "optuna/visualization/matplotlib/_parallel_coordinate.py"
TEST_PATH = "optuna_qa/parallel_coordinate_get_parallel_coordinate_plot_s3_state/files/testcase.py"
TEST_CLASS = "TestParallelCoordinateMultiObjective"
TEST_METHOD = "test_plot_multi_objective_study"
OBS_LINE = 116
OBS_COUNT = 83
VARIABLES = ["center", "obj_min", "obj_w", "p_max", "p_min", "p_w", "row", "trial_id", "value"]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)?(?: exc=.*?)? locals=(?P<locals>\{.*\})$"
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_events(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {path}")
    if not raw:
        fail("trace log is empty")
    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m or m.group("func") != TARGET_FUNC or TARGET_FILE not in m.group("file"):
            continue
        events.append(
            (m.group("event"), int(m.group("lineno")), ast.literal_eval(m.group("locals")))
        )
    if not events:
        fail("no events for target function in trace log")
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    events = parse_events(args.trace_log)
    calls = [e for e in events if e[0] == "call"]
    if len(calls) != 1:
        fail(f"expected exactly one invocation of the target, found {len(calls)}")

    state = {}
    seen = 0
    observed = None
    for idx, (event, lineno, locs) in enumerate(events):
        if event == "return":
            state = dict(locs)
        else:
            state.update(locs)
        if event == "line" and lineno == OBS_LINE:
            seen += 1
            if seen == OBS_COUNT:
                if idx + 1 >= len(events):
                    fail("no event after observation point")
                nxt_event, _, nxt_locs = events[idx + 1]
                after = dict(state)
                if nxt_event == "return":
                    after = dict(nxt_locs)
                else:
                    after.update(nxt_locs)
                observed = after
                break
    if observed is None:
        fail(f"line {OBS_LINE} executed only {seen} times (< {OBS_COUNT})")
    missing = [v for v in VARIABLES if v not in observed]
    if missing:
        fail(f"variables not bound at observation point: {missing}")
    for v in VARIABLES:
        if observed[v].endswith("..."):
            fail(f"repr of {v} truncated in trace")

    answer = {
        "observed_state": [{"value": observed[v], "variable": v} for v in sorted(VARIABLES)]
    }
    var_list = ", ".join(f"`{v}`" for v in sorted(VARIABLES))
    question = (
        f"Consider the test `{TEST_PATH}::{TEST_CLASS}::{TEST_METHOD}` (the only test method in "
        f"test class `{TEST_CLASS}` in file `{TEST_PATH}`). During this test run, the function "
        f"`optuna.visualization.matplotlib._parallel_coordinate._get_parallel_coordinate_plot` "
        f"(defined in `{TARGET_FILE}`) is invoked exactly once (indirectly, via the public "
        f"`plot_parallel_coordinate` entry point). Line numbers are absolute and 1-based in "
        f"`{TARGET_FILE}` as it exists in the repository; line {OBS_LINE} is the statement "
        f"`row.append((value - p_min) / p_w * obj_w + obj_min)` inside the inner `for row, "
        f"trial_id in zip(dims_obj_base, draw_order):` loop. Count every execution of line "
        f"{OBS_LINE} during that single invocation, across all iterations of the outer "
        f"`for dim in plot_dimensions:` loop, starting at 1 (the line {OBS_LINE - 4} "
        f"`row.append(center)` executions do NOT count). Immediately after line {OBS_LINE} has "
        f"executed for the {OBS_COUNT}rd time (i.e. after the append has taken effect, before "
        f"the next line of the function runs), what are the values of the local variables "
        f"{var_list} in that frame? Report each value as the Python `repr()` string of the "
        f"object bound to that local name at that moment (for `row`, the `repr` of the whole "
        f"list including its just-appended element; floats use Python's shortest round-trip "
        f"float repr such as `0.1` or `-2.5`, ints have no decimal point, e.g. `7`). Answer as "
        f"a JSON object with a single key `observed_state` whose value is a list of objects, "
        f"one per variable, each with exactly two keys: `variable` (the bare local variable "
        f"name, a string) and `value` (the repr string). Order the list by `variable` in "
        f"ascending lexicographic order. Every listed variable is bound at that point."
    )
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
