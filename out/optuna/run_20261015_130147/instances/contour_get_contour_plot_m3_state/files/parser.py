"""Harvest M3_ProgramState oracle for _get_contour_plot from the trace log."""

import argparse
import ast
import json
import re
import sys

TARGET_FUNC = "optuna.visualization._contour._get_contour_plot"
TARGET_FILE = "optuna/visualization/_contour.py"
TEST_PATH = "optuna_qa/contour_get_contour_plot_m3_state/files/testcase.py"
TEST_CLASS = "TestContourLogRanges"
VARIABLE = "log_range"
MIN_ENTRIES = 8

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)?(?: exc=.*?)? locals=(?P<locals>\{.*\})$"
)
RECORD_START_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ ")
HEAD_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
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
    # A record may span several physical lines (e.g. a multi-line Figure repr in retval=).
    records = []
    for line in raw:
        if RECORD_START_RE.match(line) or not records:
            records.append(line)
        else:
            records[-1] += "\n" + line
    events = []
    for rec in records:
        h = HEAD_RE.match(rec)
        # Only the target's own frame; comprehension frames (<listcomp>) are excluded.
        if not h or h.group("func") != TARGET_FUNC or TARGET_FILE not in h.group("file"):
            continue
        event = h.group("event")
        if event == "return":
            # Return locals are not needed: every assignment line is followed by a line event.
            events.append((event, int(h.group("lineno")), {}))
            continue
        m = LINE_RE.match(rec)
        if not m:
            fail(f"unparseable trace record: {rec[:200]}")
        events.append(
            (event, int(m.group("lineno")), ast.literal_eval(m.group("locals")))
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
        f"public `optuna.visualization.plot_contour` entry point. Over every invocation of "
        f"`_get_contour_plot` during the whole run (an invocation = one call of the function; "
        f"some invocations may never bind the variable), consider every value ever bound to "
        f"the local variable `{VARIABLE}` in the frame of `_get_contour_plot` itself, i.e. "
        f"each result of the statements `{VARIABLE} = [math.log10(p) for p in ...]` in both "
        f"the two-parameter branch and the multi-parameter (grid) branch, for both x and y "
        f"axes. What is the set of distinct values? Represent each value as the Python "
        f"`repr()` string of the list object bound to `{VARIABLE}` (a list of two Python "
        f"floats, e.g. a list like `[-0.75, 1.5]` would be written as the string "
        f"`\"[-0.75, 1.5]\"`, using Python's shortest round-trip float repr with full "
        f"precision and `, ` as separator). Two values are duplicates iff their repr strings "
        f"are identical; keep each distinct repr string once. Answer as a JSON object with "
        f"the single key `unique_values` whose value is the list of these repr strings sorted "
        f"in ascending order by plain Python string comparison (code-point lexicographic "
        f"order, i.e. `sorted()` on the strings, so e.g. `\"[-1...\"` sorts before `\"[0...\"`)."
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
