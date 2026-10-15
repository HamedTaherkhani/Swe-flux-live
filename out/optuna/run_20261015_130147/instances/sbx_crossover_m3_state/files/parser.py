"""Harvest M3_ProgramState oracle for SBXCrossover.crossover from the trace log."""

import argparse
import ast
import json
import re
import sys

TARGET_FUNC = "optuna.samplers.nsgaii._crossovers._sbx.SBXCrossover.crossover"
TARGET_FILE = "optuna/samplers/nsgaii/_crossovers/_sbx.py"
TEST_PATH = "optuna_qa/sbx_crossover_m3_state/files/testcase.py"
TEST_CLASS = "TestSBXCrossoverState"
VARIABLE = "c1_i"
MIN_ENTRIES = 8

RECORD_START_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ ")
HEAD_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)
LOCALS_RE = re.compile(r" locals=(?P<locals>\{.*\})$", re.S)


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
    records = []
    for line in raw:
        if RECORD_START_RE.match(line) or not records:
            records.append(line)
        else:
            records[-1] += "\n" + line
    events = []
    for rec in records:
        h = HEAD_RE.match(rec)
        if not h or h.group("func") != TARGET_FUNC or TARGET_FILE not in h.group("file"):
            continue
        m = LOCALS_RE.search(rec)
        if not m:
            fail(f"unparseable trace record: {rec[:200]}")
        events.append(
            (h.group("event"), int(h.group("lineno")), ast.literal_eval(m.group("locals")))
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
    calls = sum(1 for e in events if e[0] == "call")
    returns = sum(1 for e in events if e[0] == "return")
    if calls == 0 or calls != returns:
        fail(f"unbalanced invocations: {calls} calls, {returns} returns")

    values = set()
    for _event, _lineno, locs in events:
        v = locs.get(VARIABLE)
        if v is not None:
            if v.endswith("..."):
                fail(f"truncated repr for {VARIABLE}: {v}")
            values.add(v)
    unique = sorted(values)
    if len(unique) < MIN_ENTRIES:
        fail(f"too few distinct values for {VARIABLE}: {len(unique)}")

    question = (
        f"Run every test method of the unittest class `{TEST_CLASS}` in `{TEST_PATH}` "
        f"(i.e. all pytest ids `{TEST_PATH}::{TEST_CLASS}::test_*`; the answer aggregates "
        "over ALL of them, and since it is a set the execution order does not matter). "
        "Consider every invocation (each call of the function during the run) of "
        f"`{TARGET_FUNC}` defined in `{TARGET_FILE}`. Inside that function, the loop "
        "`for c1_i, c2_i, x1_i, x2_i in zip(c1, c2, parents_params[0], parents_params[1]):` "
        "binds the local variable `c1_i` once per loop iteration. Collect the value bound to "
        "`c1_i` in EVERY iteration of that loop across ALL invocations, and report the set of "
        "distinct values. Each value must be written as the Python `repr()` string of the "
        "object exactly as bound (it is a NumPy scalar, so under the installed NumPy the repr "
        "has the form `np.float64(<shortest round-trip float repr>)`, e.g. `np.float64(-0.25)` "
        "or `np.float64(1.5e-07)`; do not round or reformat). Two values are the same iff their "
        "repr strings are identical; remove duplicates. Sort the strings ascending using plain "
        "Python string ordering (`sorted()` on the repr strings, i.e. Unicode code-point order, "
        "NOT numeric order). Answer as JSON `{\"unique_values\": [<str>, ...]}`."
    )

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": question,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    print(f"invocations={calls} distinct={len(unique)}")


if __name__ == "__main__":
    main()
