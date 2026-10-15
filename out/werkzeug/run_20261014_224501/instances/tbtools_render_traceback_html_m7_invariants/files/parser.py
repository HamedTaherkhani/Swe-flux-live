#!/usr/bin/env python
"""Trace -> oracle.json for tbtools_render_traceback_html_m7_invariants (M7_Invariants)."""
import argparse
import ast
import json
import os
import re
import sys

TARGET_SUFFIX = ".DebugTraceback.render_traceback_html"
TARGET_FILE = "src/werkzeug/debug/tbtools.py"
TEST_PATH = "werkzeug_qa/tbtools_render_traceback_html_m7_invariants/files/testcase.py"
TEST_CLASS = "RenderTracebackScenarios"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
LOCALS_RE = re.compile(r" locals=(?P<locals>\{.*\})$")

# Lines whose execution changes the length of the lists `row_parts` / `rows`.
LINE_ROW_PARTS_RESET = 283
LINE_ROW_PARTS_APPEND = (286, 291)
LINE_ROWS_APPEND = 293

# predicate text -> (observation line, evaluator(state))
PREDICATES = {
    "info == ''": (291, lambda st: st["locals"]["info"] == "''"),
    "is_syntax_error": (303, lambda st: st["locals"]["is_syntax_error"] == "True"),
    "len(rows) < 3": (289, lambda st: st["rows_len"] < 3),
    "len(rows) < 2": (288, lambda st: st["rows_len"] < 2),
    "not is_syntax_error": (312, lambda st: st["locals"]["is_syntax_error"] != "True"),
    "not mark_library": (282, lambda st: st["locals"]["mark_library"] != "True"),
}

PRED_LINES = "; ".join(
    f"`{p}` observed at line {PREDICATES[p][0]}" for p in sorted(PREDICATES)
)

QUESTION = (
    f"Run the whole test class `{TEST_CLASS}` in `{TEST_PATH}` with pytest (all of its "
    f"test methods, e.g. pytest id `{TEST_PATH}::{TEST_CLASS}::test_plain_recursion`); the "
    "answer aggregates over ALL test methods of the class. Consider every invocation of the "
    f"method `DebugTraceback.render_traceback_html` defined in `{TARGET_FILE}` (qualname "
    "`werkzeug.debug.tbtools.DebugTraceback.render_traceback_html`, lines 272-322; it is reached "
    "indirectly when `DebuggedApplication` renders its error page). An invocation is one call of "
    "that method (not of nested comprehension frames or of callees such as "
    "`DebugFrameSummary.render_html`). "
    "An 'observation at line N' happens every time line N of that file is about to execute in "
    "the frame of `render_traceback_html` (a Python 'line' event for line N, i.e. before the "
    "statement on line N runs). For the `for` statements on lines 282 and 288 this includes "
    "every evaluation of the loop header: once per loop iteration plus the final evaluation "
    "that finds the iterable exhausted. At each observation, a predicate is evaluated on the "
    "current values of the method's local variables at that moment (so a variable assigned on "
    "line N itself still holds its previous value; e.g. at line 291 `info` already holds "
    "the value computed on line 290 for the current frame, while at lines 288 and 289 `rows` "
    "holds only the rows appended by line 293 so far). Predicates are evaluated with ordinary "
    "Python semantics on the real runtime objects. The candidate predicates, each with its single "
    f"observation line, are: {PRED_LINES}. "
    "For each predicate report: `predicate` = the predicate text exactly as written above "
    "inside the backticks (a JSON string, no backticks); `observations` = total number of "
    "observations of its line summed over all invocations in all test methods; `violations` "
    "= how many of those observations had the predicate evaluate to false; `held_always` = "
    "true iff `violations` is 0 AND `observations` is at least 1 (a predicate whose line is "
    "never reached is reported with `observations: 0`, `violations: 0`, `held_always: false`). "
    "Return a JSON object `{\"invariant_report\": [...]}` with exactly one entry per candidate "
    "predicate (six entries), each having keys `held_always` (JSON boolean), `observations` "
    "(int), `predicate` (str), `violations` (int), sorted by `predicate` ascending using plain "
    "Python string comparison (code-point order); predicate texts are unique so no tie-break "
    "is needed."
)

TEMPLATE = {
    "invariant_report": [
        {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
    ]
}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log missing: {args.trace_log}")
    with open(args.trace_log, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    if not raw:
        fail("trace log is empty")

    counts = {p: [0, 0] for p in PREDICATES}
    by_line = {}
    for p, (line, _) in PREDICATES.items():
        by_line.setdefault(line, []).append(p)

    state = None
    invocations = 0
    target_events = 0

    for text in raw:
        m = LINE_RE.match(text)
        if not m:
            continue
        if not m.group("func").endswith(TARGET_SUFFIX):
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        target_events += 1
        event = m.group("event")
        lineno = int(m.group("lineno"))
        lm = LOCALS_RE.search(m.group("rest"))
        changed = ast.literal_eval(lm.group("locals")) if lm else {}

        if event == "call":
            invocations += 1
            state = {"locals": dict(changed), "row_parts_len": None, "rows_len": 0}
            continue
        if state is None:
            fail(f"event before any call: {text}")
        state["locals"].update(changed)
        if event == "return":
            state = None
            continue
        if event != "line":
            continue

        for p in by_line.get(lineno, ()):
            ok = PREDICATES[p][1](state)
            counts[p][0] += 1
            if not ok:
                counts[p][1] += 1

        if lineno == LINE_ROW_PARTS_RESET:
            state["row_parts_len"] = 0
        elif lineno in LINE_ROW_PARTS_APPEND:
            state["row_parts_len"] += 1
        elif lineno == LINE_ROWS_APPEND:
            state["rows_len"] += 1

    if target_events == 0 or invocations == 0:
        fail("no events for DebugTraceback.render_traceback_html in trace")

    report = []
    for p in sorted(PREDICATES):
        obs, vio = counts[p]
        report.append(
            {
                "held_always": bool(obs > 0 and vio == 0),
                "observations": obs,
                "predicate": p,
                "violations": vio,
            }
        )

    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": {"invariant_report": report},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={invocations} target_events={target_events}")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
