#!/usr/bin/env python
"""Derive the M7_Invariants oracle for Tuple._bind_to_schema from a trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/fields.py"
TARGET_QUAL_SUFFIX = "fields.Tuple._bind_to_schema"
TEST_REL = "marshmallow_qa/fields_bind_to_schema_m7_invariants/files/testcase.py"
TEST_CLASS = "TupleBindInvariantTest"

LINE_RE = re.compile(
    r"\s(\S+):(\d+) (\S+) event=(\w+)(?: retval=.*?| exc=.*?)? locals=(\{.*\})\s*$"
)
FLAG_RES = {
    "required": re.compile(r", required=(True|False), load_only="),
    "allow_none": re.compile(r", allow_none=(True|False), error_messages="),
}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def cls_name(r):
    m = re.match(r"<fields\.(\w+)\(", r)
    if not m:
        fail(f"cannot read field class from repr: {r[:80]}")
    return m.group(1)


def flag(r, name):
    m = FLAG_RES[name].search(r)
    if not m:
        fail(f"cannot read {name} from repr: {r[:120]}")
    return m.group(1) == "True"


def field_name_value(r):
    if r.endswith("..."):
        fail("truncated field_name repr")
    return ast.literal_eval(r)


# (observation line, predicate text, evaluator(locals, frame_state) -> bool or None when not evaluated)
PREDICATES = [
    (846, "line 846: isinstance(parent, Tuple)",
     lambda v, st: v["parent"].startswith("<fields.Tuple(")),
    (846, "line 846: '_' not in field_name",
     lambda v, st: "_" not in field_name_value(v["field_name"])),
    (849, "line 849: isinstance(field, Tuple)",
     lambda v, st: cls_name(v["field"]) == "Tuple"),
    (849, "line 849: len(new_tuple_fields) < 4",
     lambda v, st: st["appended"] < 4),
    (849, "line 849: field.required or field.allow_none",
     lambda v, st: flag(v["field"], "required") or flag(v["field"], "allow_none")),
    (850, "line 850 [only where isinstance(new_field, fields.Dict)]: new_field.required",
     lambda v, st: (flag(v["new_field"], "required") if cls_name(v["new_field"]) == "Dict" else None)),
    (853, "line 853: len(new_tuple_fields) <= 7",
     lambda v, st: st["appended"] <= 7),
    (853, "line 853: len(new_tuple_fields) % 2 == 1",
     lambda v, st: st["appended"] % 2 == 1),
]


def analyse(trace_path):
    p = Path(trace_path)
    if not p.is_file():
        fail(f"trace log missing: {trace_path}")
    text = p.read_text(encoding="utf-8")
    if not text.strip():
        fail("trace log is empty")
    stats = {text_: [0, 0] for _, text_, _ in PREDICATES}
    stack = []
    n_events = 0
    for raw in text.splitlines():
        m = LINE_RE.search(raw)
        if not m:
            continue
        fname, lineno, func, event, locs = m.groups()
        if not fname.endswith(TARGET_REL) or not func.endswith(TARGET_QUAL_SUFFIX):
            continue
        n_events += 1
        lineno = int(lineno)
        diff = ast.literal_eval(locs)
        if event == "call":
            stack.append({"locals": dict(diff), "appended": 0})
            continue
        if not stack:
            fail("event outside of a traced call")
        st = stack[-1]
        st["locals"].update(diff)
        if event in ("return", "exception"):
            if event == "return":
                stack.pop()
            continue
        if event != "line":
            continue
        for obs_line, text_, fn in PREDICATES:
            if obs_line != lineno:
                continue
            res = fn(st["locals"], st)
            if res is None:
                continue
            stats[text_][0] += 1
            if not res:
                stats[text_][1] += 1
        if lineno == 851:
            st["appended"] += 1
    if n_events == 0:
        fail("no events for Tuple._bind_to_schema in trace")
    if stack:
        fail("unbalanced call/return events in trace")
    report = []
    for text_ in sorted(stats):
        obs, vio = stats[text_]
        report.append({
            "held_always": obs > 0 and vio == 0,
            "observations": obs,
            "predicate": text_,
            "violations": vio,
        })
    return report


def build_question():
    preds = "\n".join(f"  - `{t}`" for t in sorted(t for _, t, _ in PREDICATES))
    return f"""Consider the pytest test class `{TEST_REL}::{TEST_CLASS}` (12 test methods, pytest ids `{TEST_REL}::{TEST_CLASS}::test_...`). Run ALL test methods of this class (e.g. `pytest {TEST_REL}::{TEST_CLASS}`); the answer aggregates over every invocation of the target that happens while any of these test methods runs. Counts are totals across all methods; method execution order does not affect them.

Target function: `Tuple._bind_to_schema` (qualname `marshmallow.fields.Tuple._bind_to_schema`) in `{TARGET_REL}` (the `def` is on line 845). An invocation is one call of exactly this function, whether made directly by the test code or recursively from line 850 of the function itself (when an element of `self.tuple_fields` is itself a `Tuple`), or from any other caller during the test (e.g. a `Tuple` bound only to serve as a parent). Calls of other classes' `_bind_to_schema` (e.g. `Field._bind_to_schema` via `super()` on line 846, or `DateTime`'s override) are NOT invocations and contribute no observations, but their side effects on objects are real.

Candidate predicates (each prefixed by its observation line; line numbers are absolute, 1-based line numbers in `{TARGET_REL}` as it exists in the repository):
{preds}

Observation semantics:
  - A predicate prefixed `line N:` is evaluated once each time line N is about to execute (a Python `line` event for line N in a frame of the target), using the values the target's local variables (`self`, `field_name`, `parent`, `new_tuple_fields`, `field`, `new_field`) hold at that moment, i.e. BEFORE line N runs. So at line 849 `field` is the current loop element and `new_tuple_fields` holds only the elements appended in earlier iterations of the same invocation; at line 846 the `super()` call has not run yet. Line 849 therefore produces exactly one observation per loop iteration, line 846 and line 853 exactly one per invocation (an invocation over an empty `tuple_fields` still reaches line 853).
  - `Tuple` means `marshmallow.fields.Tuple`; `isinstance` uses the real classes. `field.required` and `field.allow_none` are the instance attributes (note `allow_none` may be set implicitly by the `Field` constructor); `or` is Python's boolean `or` and the predicate is judged by truthiness.
  - The predicate with the bracketed guard `[only where isinstance(new_field, fields.Dict)]` is evaluated only at line-850 events where the guard is true; events where the guard is false are not observations at all (they count neither as observations nor as violations).
  - `observations` = number of times the predicate was evaluated; `violations` = number of those evaluations that were false.
  - `held_always` = true iff `observations > 0` and `violations == 0`. A predicate that was never evaluated is reported with `observations: 0`, `violations: 0`, `held_always: false`.

Answer format: JSON object `{{"invariant_report": [...]}}` with exactly one entry per candidate predicate above, each `{{"held_always": bool, "observations": int, "predicate": str, "violations": int}}`. `predicate` is the predicate text copied verbatim exactly as listed above (including its `line N:` prefix and any bracketed guard, without the surrounding backticks). Sort entries by `predicate` ascending using plain Python string comparison (code-point order); predicate strings are unique so no tie-break is needed. Booleans are JSON `true`/`false`; counts are JSON integers."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    report = analyse(args.trace_log)
    oracle = {
        "question_kind": "M7_Invariants",
        "question": build_question(),
        "template_answer": {"invariant_report": [
            {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
        ]},
        "oracle_answer": {"invariant_report": report},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
