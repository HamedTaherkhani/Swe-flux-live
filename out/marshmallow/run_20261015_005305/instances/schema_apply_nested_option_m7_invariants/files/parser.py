#!/usr/bin/env python
"""Derive the M7_Invariants oracle for Schema.__apply_nested_option from a trace log."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_REL = "src/marshmallow/schema.py"
TARGET_QUAL_SUFFIX = "Schema.__apply_nested_option"
TEST_REL = "marshmallow_qa/schema_apply_nested_option_m7_invariants/files/testcase.py"
TEST_CLASS = "ApplyNestedOptionsInvariantTest"

LINE_RE = re.compile(r"\s(\S+):(\d+) (\S+) event=(\w+)(?: retval=.*?)? locals=(\{.*\})\s*$")
WRAP_RE = re.compile(r"^(?:OrderedSet|defaultdict)\((.*)\)$", re.S)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_value(text):
    """Turn a traced repr string into a Python value (OrderedSet -> list, defaultdict -> dict)."""
    m = WRAP_RE.match(text)
    if m:
        inner = m.group(1)
        if inner.startswith("<class "):
            inner = inner.split(", ", 1)[1] if ", " in inner else "{}"
        return ast.literal_eval(inner) if inner else []
    if text.endswith("..."):
        fail(f"truncated repr in trace: {text[:80]}")
    return ast.literal_eval(text)


# (observation line, predicate text, evaluator over parsed locals)
PREDICATES = [
    (970, "line 970: '.' not in nested_names", lambda v: "." not in v["nested_names"]),
    (975, "line 975: len(options) >= 2", lambda v: len(v["options"]) >= 2),
    (
        977,
        "line 977: len(original_options) >= len(options)",
        lambda v: len(v["original_options"]) >= len(v["options"]),
    ),
    (980, "line 980: len(new_options) == len(options)", lambda v: len(v["new_options"]) == len(v["options"])),
    (980, "line 980: len(new_options) > 0", lambda v: len(v["new_options"]) > 0),
    (980, "line 980: len(new_options) <= len(options)", lambda v: len(v["new_options"]) <= len(v["options"])),
]


def build_question():
    preds = "\n".join(f"  - `{text}`" for _, text, _ in sorted(PREDICATES, key=lambda p: p[1]))
    return f"""Consider the pytest test class `{TEST_REL}::{TEST_CLASS}` (12 test methods). Run ALL test methods of this class (e.g. `pytest {TEST_REL}::{TEST_CLASS}`); the answer aggregates over every invocation of the target that happens while any of these test methods runs (counts are totals across all methods; their execution order does not affect the answer).

Target function: `Schema.__apply_nested_option` (name-mangled private method; qualname `marshmallow.schema.Schema.__apply_nested_option`) in `{TARGET_REL}`. The test never calls it directly: it is reached via `Schema.__init__` -> `Schema._normalize_nested_options`, including for nested child schemas that are instantiated lazily (e.g. when `Nested.schema` is first accessed during `dump`). Every such invocation counts, whichever schema class it runs on.

Candidate predicates (each prefixed by its observation line; line numbers are absolute, 1-based line numbers in `{TARGET_REL}` as it exists in the repository):
{preds}

Observation semantics: a predicate prefixed `line N:` is evaluated once each time line N of the target begins executing (i.e. at the Python trace `line` event for line N, BEFORE that line's statement runs), using the target frame's local variables as they are at that instant. So at line 970 `nested_names` is the value just bound by the `for` on line 969; at line 975 `options`, `new_options` and `original_options` are the values bound by lines 972-974; at line 980 `new_options` reflects any `|=` / `&=` already applied on lines 977/979. `len(...)` is the ordinary Python `len` of the actual local object (an `OrderedSet`, list, tuple, etc.); `options` is the per-parent list built on line 970 and may contain duplicates, while `new_options` (an `OrderedSet`) does not. Predicates are evaluated in the target's own frame only (the list comprehension on line 966 is not an observation).

For each predicate report:
  - `predicate`: the predicate text exactly as written above, including the `line N: ` prefix (a JSON string; e.g. a hypothetical predicate written `line 1: x > 0` would be reported as "line 1: x > 0");
  - `observations`: integer, the number of times it was evaluated (number of executions of its observation line, summed over all invocations in all test methods);
  - `violations`: integer, the number of those evaluations that were false;
  - `held_always`: JSON boolean, `true` iff `violations == 0` AND `observations > 0`. A predicate whose observation line never executes is reported with `observations: 0`, `violations: 0`, `held_always: false`.

Answer format: a JSON object `{{"invariant_report": [...]}}` with exactly one entry per candidate predicate (6 entries), each an object with exactly the keys `held_always`, `observations`, `predicate`, `violations`. Sort the list by `predicate` ascending using plain Python string ordering (code-point order); predicate strings are all distinct, so no tie-break is needed."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    trace = Path(args.trace_log)
    if not trace.is_file() or trace.stat().st_size == 0:
        fail(f"trace log missing or empty: {trace}")

    stats = {text: [0, 0] for _, text, _ in PREDICATES}
    by_line = {}
    for line_no, text, fn in PREDICATES:
        by_line.setdefault(line_no, []).append((text, fn))

    state = None
    n_calls = 0
    n_events = 0
    for raw in trace.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.search(raw)
        if not m:
            continue
        path, lineno, func, event, locs = m.groups()
        if not path.endswith(TARGET_REL) or not func.endswith(TARGET_QUAL_SUFFIX):
            continue
        n_events += 1
        lineno = int(lineno)
        changed = ast.literal_eval(locs)
        if event == "call":
            if state is not None:
                fail("nested/unterminated invocation of target in trace")
            n_calls += 1
            state = {}
        if state is None:
            fail(f"event outside an invocation: {raw[:120]}")
        if event == "line" and lineno in by_line:
            # locals logged on a line event are the values at the moment it fires
            for k, v in changed.items():
                state[k] = v
            values = {k: parse_value(v) for k, v in state.items() if k != "self"}
            for text, fn in by_line[lineno]:
                stats[text][0] += 1
                if not fn(values):
                    stats[text][1] += 1
            continue
        for k, v in changed.items():
            state[k] = v
        if event in ("return", "exception"):
            if event == "exception":
                fail("unexpected exception inside target")
            state = None

    if n_calls == 0 or n_events == 0:
        fail("no events for target function in trace")
    if state is not None:
        fail("trace ended mid-invocation")

    report = []
    for text in sorted(stats):
        obs, viol = stats[text]
        report.append(
            {
                "held_always": bool(obs > 0 and viol == 0),
                "observations": obs,
                "predicate": text,
                "violations": viol,
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
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))
    print(f"invocations={n_calls} events={n_events}", file=sys.stderr)


if __name__ == "__main__":
    main()
