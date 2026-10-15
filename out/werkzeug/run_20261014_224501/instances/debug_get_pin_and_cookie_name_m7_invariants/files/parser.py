#!/usr/bin/env python
"""Derive the M7_Invariants oracle for werkzeug.debug.get_pin_and_cookie_name."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FUNC = "werkzeug.debug.get_pin_and_cookie_name"
TARGET_FILE = "src/werkzeug/debug/__init__.py"
TEST_FILE = "werkzeug_qa/debug_get_pin_and_cookie_name_m7_invariants/files/testcase.py"
TEST_CLASS = "TestPinAndCookieInvariants"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=(?P<retval>.*?)| exc=.*?)? locals=(?P<locals>\{.*\})$"
)

# (observation line, source text of that line, predicate text, evaluator)
PREDICATES = [
    (159, "return None, None", "pin.isdecimal()", lambda v: v["pin"].isdecimal()),
    (197, "if not bit:", "isinstance(bit, str)", lambda v: isinstance(v["bit"], str)),
    (208, "if num is None:", "rv is None", lambda v: v["rv"] is None),
    (
        216,
        "if len(num) % group_size == 0:",
        "len(num) % group_size == 0",
        lambda v: len(v["num"]) % v["group_size"] == 0,
    ),
    (216, "if len(num) % group_size == 0:", "len(num) >= 2", lambda v: len(v["num"]) >= 2),
    (225, "return rv, cookie_name", "len(rv) != 10", lambda v: len(v["rv"]) != 10),
]


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_source(root):
    src = (root / TARGET_FILE).read_text().splitlines()
    for line, text, _, _ in PREDICATES:
        if src[line - 1].strip() != text:
            fail(f"source line {line} is {src[line - 1].strip()!r}, expected {text!r}")


def build_question():
    bullets = "\n".join(
        f"  - predicate `{pred}` — observed at line {line} (`{text}`)"
        for line, text, pred, _ in PREDICATES
    )
    return f"""\
Run the whole pytest class `{TEST_FILE}::{TEST_CLASS}` (ALL 12 of its test \
methods; the answer aggregates over every one of them — counts are totals \
across the entire class run, independent of method order). Consider every \
invocation (one call of the function, wherever it comes from) of the \
module-level function `{TARGET_FUNC}` defined in `{TARGET_FILE}`.

Candidate invariants. Each predicate below is a Python expression over the \
target function's own local variables, evaluated at an observation point \
given as an absolute 1-based line number in `{TARGET_FILE}` (as it exists in \
the repository). An OBSERVATION happens each time that line is about to \
execute inside the target function's own frame (i.e. a Python line event for \
that line — for loop-body lines, once per loop iteration that reaches it); \
the predicate is evaluated on the values the locals hold at that moment, \
i.e. BEFORE the statement on that line runs (so at line 216 `group_size` is \
the current loop value, at line 225 `rv` is the value about to be returned); \
`len()` of a str counts code points. Lines executed inside the generator \
expression on lines 217-220 are a separate frame and are never observations.
{bullets}

For each predicate report:
- `predicate`: the predicate text exactly as written between backticks above \
(e.g. a hypothetical predicate `x > 0` is reported as the string "x > 0");
- `observations`: the total number of observations of its line over the \
whole class run (int);
- `violations`: how many of those observations evaluated to false (int);
- `held_always`: true iff `violations == 0` AND `observations > 0`. A \
predicate whose line is never executed is reported with `observations: 0`, \
`violations: 0`, `held_always: false`.

Answer with JSON `{{"invariant_report": [...]}}` containing exactly one object \
per predicate (all {len(PREDICATES)} of them), with keys `held_always` (JSON \
bool), `observations` (int), `predicate` (str), `violations` (int), sorted \
ascending by the `predicate` string using plain Python string comparison \
(code-point order); predicates are all distinct, so no tie-break is needed."""


def parse_value(raw):
    try:
        return ast.literal_eval(raw)
    except Exception:
        return ("<unparsable>", raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.exists():
        fail(f"trace log missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")

    root = Path(__file__).resolve()
    for parent in root.parents:
        if (parent / TARGET_FILE).exists():
            check_source(parent)
            break
    else:
        fail("cannot locate target source")

    by_line = {}
    for p in PREDICATES:
        by_line.setdefault(p[0], []).append(p)
    obs = {p[2]: 0 for p in PREDICATES}
    viol = {p[2]: 0 for p in PREDICATES}
    n_events = 0
    n_calls = 0
    state = None

    for raw in text.splitlines():
        m = LINE_RE.match(raw)
        if not m or m.group("func") != TARGET_FUNC:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        n_events += 1
        event = m.group("event")
        changed = ast.literal_eval(m.group("locals"))
        if event == "call":
            n_calls += 1
            state = {}
        if state is None:
            fail("event before any call")
        for k, v in changed.items():
            state[k] = parse_value(v)
        if event == "line":
            line = int(m.group("line"))
            for _, _, pred, fn in by_line.get(line, []):
                obs[pred] += 1
                try:
                    ok = bool(fn(state))
                except Exception as e:
                    fail(f"predicate {pred!r} failed at line {line}: {e!r} state={state}")
                if not ok:
                    viol[pred] += 1
        if event == "return":
            state = None

    if n_events == 0 or n_calls == 0:
        fail("zero events for target function in trace")

    report = []
    for pred in sorted(obs):
        report.append(
            {
                "held_always": obs[pred] > 0 and viol[pred] == 0,
                "observations": obs[pred],
                "predicate": pred,
                "violations": viol[pred],
            }
        )

    oracle = {
        "question_kind": "M7_Invariants",
        "question": build_question(),
        "template_answer": {
            "invariant_report": [
                {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
            ]
        },
        "oracle_answer": {"invariant_report": report},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"calls={n_calls} events={n_events}")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
