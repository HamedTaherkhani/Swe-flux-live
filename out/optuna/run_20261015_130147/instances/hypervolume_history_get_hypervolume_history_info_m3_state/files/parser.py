"""Harvest M3_ProgramState oracle for _get_hypervolume_history_info from the trace log."""

import argparse
import ast
import json
import re
import sys

TARGET_FUNC = "optuna.visualization._hypervolume_history._get_hypervolume_history_info"
TARGET_FILE = "optuna/visualization/_hypervolume_history.py"
TEST_PATH = "optuna_qa/hypervolume_history_get_hypervolume_history_info_m3_state/files/testcase.py"
TEST_CLASS = "TestHypervolumeHistoryStates"
VARIABLE = "hypervolume"
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
        # Only the target's own frame (comprehension/genexpr frames are excluded).
        if not h or h.group("func") != TARGET_FUNC or TARGET_FILE not in h.group("file"):
            continue
        m = LOCALS_RE.search(rec)
        if not m:
            fail(f"unparseable trace record: {rec[:200]}")
        events.append((h.group("event"), int(h.group("lineno")), ast.literal_eval(m.group("locals"))))
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

    # Every binding of the variable is followed by a line or return event in the same
    # frame, so collecting all logged reprs yields every value it was ever bound to.
    values = set()
    for _event, _lineno, locs in events:
        if VARIABLE in locs:
            v = locs[VARIABLE]
            if v.endswith("..."):
                fail(f"repr of {VARIABLE} truncated in trace: {v}")
            values.add(v)
    answer_values = sorted(values)
    if len(answer_values) < MIN_ENTRIES:
        fail(f"only {len(answer_values)} distinct values of {VARIABLE} (< {MIN_ENTRIES})")

    question = (
        f"Run ALL test methods of the test class `{TEST_CLASS}` in the file `{TEST_PATH}` "
        f"(pytest id `{TEST_PATH}::{TEST_CLASS}`; the answer aggregates over every test "
        f"method in that class, regardless of the order in which they run). Each test reaches "
        f"the function `{TARGET_FUNC}` (defined in `{TARGET_FILE}`) indirectly through the "
        f"public `optuna.visualization.plot_hypervolume_history` entry point. Over every "
        f"invocation of `_get_hypervolume_history_info` during the whole run (an invocation = "
        f"one call of the function), consider every value ever bound to the local variable "
        f"`{VARIABLE}` in the frame of `_get_hypervolume_history_info` itself: its initial "
        f"binding `{VARIABLE} = 0.0`, the result of EACH `{VARIABLE} += ...` augmented "
        f"assignment, and the result of EACH `{VARIABLE} -= ...` augmented assignment -- "
        f"including transient values that are immediately overwritten by the next statement "
        f"(e.g. the value right after `+=` and before `-=` in the same loop iteration). "
        f"What is the set of distinct values? Represent each value as the Python `repr()` "
        f"string of the object bound to `{VARIABLE}` at that moment, exactly as produced in "
        f"this environment (NumPy 2.x): a plain Python float is written like `\"2.5\"`, while "
        f"a NumPy scalar is written with its NumPy 2 repr such as `\"np.float64(2.5)\"`; the "
        f"type matters, so a Python float and a NumPy float64 with equal numeric value are "
        f"two different strings. Two values are duplicates iff their repr strings are "
        f"identical; keep each distinct repr string once. Answer as a JSON object with the "
        f"single key `unique_values` whose value is the list of these repr strings sorted in "
        f"ascending order by plain Python string comparison (code-point lexicographic order, "
        f"i.e. `sorted()` on the strings, so e.g. `\"np.float64(10.5)\"` sorts before "
        f"`\"np.float64(9.5)\"`, and a plain-float string such as `\"3.5\"` sorts before any "
        f"`\"np...\"` string)."
    )
    oracle = {
        "question_kind": "M3_ProgramState",
        "question": question,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": answer_values},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
