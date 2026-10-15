#!/usr/bin/env python
"""Trace -> oracle.json for repr_dump_object_m7_invariants (M7_Invariants)."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_SUFFIX = ".DebugReprGenerator.dump_object"
TARGET_FILE = "src/werkzeug/debug/repr.py"
TEST_PATH = "werkzeug_qa/repr_dump_object_m7_invariants/files/testcase.py"
TEST_CLASS = "DumpObjectScenarios"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
LOCALS_RE = re.compile(r" locals=(?P<locals>\{.*\})$")

_NOVAL = object()


def _key(st):
    raw = st["locals"].get("key", None)
    if raw is None:
        raise SystemExit("ERROR: `key` not available at observation point")
    return ast.literal_eval(raw)


def _items_len(st):
    if st["items_len"] is None:
        raise SystemExit("ERROR: items is None at a len(items) observation")
    return st["items_len"]


# predicate text -> (observation line, evaluator(state))
PREDICATES = {
    "isinstance(key, str)": (250, lambda st: isinstance(_key(st), str)),
    "len(items) < 6": (253, lambda st: _items_len(st) < 6),
    "items is not None": (254, lambda st: st["items_len"] is not None),
    "key.startswith('__')": (259, lambda st: _key(st).startswith("__")),
    "len(items) < 3": (261, lambda st: _items_len(st) < 3),
    "len(items) > 0": (263, lambda st: _items_len(st) > 0),
}

PRED_LINES = "; ".join(
    f"`{p}` observed at line {PREDICATES[p][0]}" for p in sorted(PREDICATES)
)

QUESTION = (
    f"Run the whole test class `{TEST_CLASS}` in `{TEST_PATH}` with pytest (all of its test "
    f"methods, e.g. pytest id `{TEST_PATH}::{TEST_CLASS}::test_empty_dict`); the answer "
    "aggregates over ALL test methods of the class (all invocations in all methods, summed). "
    "Consider every invocation of the method `DebugReprGenerator.dump_object` defined in "
    f"`{TARGET_FILE}` (qualname `werkzeug.debug.repr.DebugReprGenerator.dump_object`, lines "
    "242-264). An invocation is one call of that method; only its own frame matters (not "
    "callees such as `DebugReprGenerator.repr`, `getattr` or `__getattr__` hooks). "
    "An 'observation at line N' happens every time line N of that file is about to execute in "
    "the frame of `dump_object` (a Python 'line' event for line N, i.e. before the statement "
    "on line N runs; one observation per execution of that line, so a line inside a loop is "
    "observed once per iteration that reaches it). At each observation a predicate is "
    "evaluated with ordinary Python semantics on the current runtime values of the method's "
    "local variables at that moment (so `key` is the value bound by the most recent loop "
    "header, and `items` reflects only the appends that have actually completed so far in "
    "this invocation; an append on line 259 whose argument raised did not happen). "
    "The candidate predicates, each with its observation line, are: "
    f"{PRED_LINES}. "
    "For each predicate report: `predicate` = the predicate text exactly as written between "
    "the backticks above (e.g. a predicate written `x is y` is reported as the string "
    "\"x is y\"); `observations` = total number of observations of its line across all "
    "invocations in all test methods (int); `violations` = how many of those evaluations were "
    "False (int); `held_always` = true iff `violations` is 0 and `observations` is greater "
    "than 0 (a predicate whose line is never observed is reported with observations 0, "
    "violations 0, held_always false). Answer as JSON "
    "`{\"invariant_report\": [{\"held_always\": bool, \"observations\": int, "
    "\"predicate\": str, \"violations\": int}, ...]}` with exactly one entry per candidate "
    "predicate, sorted by `predicate` ascending using plain Python string ordering "
    "(code-point order; predicate strings are unique so no tie-break is needed). Use JSON "
    "`true`/`false` for booleans."
)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    return ap.parse_args()


def main():
    args = parse_args()
    if not os.path.isfile(args.trace_log):
        raise SystemExit(f"ERROR: trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw_lines = fh.read().splitlines()
    if not raw_lines:
        raise SystemExit("ERROR: trace log is empty")

    counts = {p: [0, 0] for p in PREDICATES}
    by_line = {}
    for p, (ln, _) in PREDICATES.items():
        by_line.setdefault(ln, []).append(p)

    st = None
    n_calls = 0
    n_events = 0
    for raw in raw_lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE) or not m.group("func").endswith(TARGET_SUFFIX):
            continue
        n_events += 1
        event = m.group("event")
        lineno = int(m.group("lineno"))
        lm = LOCALS_RE.search(m.group("rest"))
        changed = ast.literal_eval(lm.group("locals")) if lm else {}

        if event == "call":
            if st is not None:
                raise SystemExit("ERROR: nested dump_object invocation not expected")
            n_calls += 1
            st = {"locals": dict(changed), "items_len": None, "pending": None}
            continue
        if st is None:
            raise SystemExit("ERROR: event outside of an invocation")
        st["locals"].update(changed)

        if event == "exception":
            if lineno == 259:
                st["pending"] = None  # the append did not complete
            continue
        if event == "return":
            st = None
            continue
        # line event: first apply effect of the previously executed line
        if st["pending"] is not None:
            st["items_len"] = st["pending"]
            st["pending"] = None
        for p in by_line.get(lineno, ()):
            ok = PREDICATES[p][1](st)
            counts[p][0] += 1
            if not ok:
                counts[p][1] += 1
        # then record the effect of executing this line
        if lineno in (244,):
            st["items_len"] = None
        elif lineno in (248, 255):
            st["pending"] = 0
        elif lineno == 251:
            st["pending"] = None
            st["items_len"] = None
        elif lineno in (253, 259):
            st["pending"] = _items_len(st) + 1

    if n_calls == 0 or n_events == 0:
        raise SystemExit("ERROR: zero events for target function in trace")

    report = [
        {
            "held_always": counts[p][1] == 0 and counts[p][0] > 0,
            "observations": counts[p][0],
            "predicate": p,
            "violations": counts[p][1],
        }
        for p in sorted(PREDICATES)
    ]
    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "invariant_report": [
                {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
            ]
        },
        "oracle_answer": {"invariant_report": report},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))
    print(f"invocations={n_calls} events={n_events}", file=sys.stderr)


if __name__ == "__main__":
    main()
