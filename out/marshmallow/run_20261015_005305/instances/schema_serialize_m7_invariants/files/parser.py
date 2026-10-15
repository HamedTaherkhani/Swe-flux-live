#!/usr/bin/env python
"""Parse the line-level trace of ``Schema._serialize`` into an M7 invariant report."""

import argparse
import ast
import json
import re
import sys

TARGET_SUFFIX = "Schema._serialize"
TARGET_PATH = "src/marshmallow/schema.py"

LINE_RE = re.compile(r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) ")

P_LEN_OBJ = "len(obj) > 0"
P_LEN_RET = "len(ret) < 3"
P_NOT_NONE = "value is not None"
P_KEY_EQ = "key == attr_name"
P_IS_STR = "type(value) is str"
P_ISLOWER = "attr_name.islower()"
P_OBJ_NN = "obj is not None"

# predicate -> observed line
OBS_LINE = {
    P_LEN_OBJ: 538,
    P_OBJ_NN: 539,
    P_LEN_RET: 540,
    P_NOT_NONE: 542,
    P_ISLOWER: 543,
    P_KEY_EQ: 545,
    P_IS_STR: 545,
}

QUESTION = """\
Test file: `marshmallow_qa/schema_serialize_m7_invariants/files/testcase.py`, test class `SerializeInvariantTest` (pytest id prefix `marshmallow_qa/schema_serialize_m7_invariants/files/testcase.py::SerializeInvariantTest`). Run ALL 12 test methods of the class (test_01 ... test_12); the answer aggregates over every one of them.

Target function: `marshmallow.schema.Schema._serialize` in `src/marshmallow/schema.py` (the method whose `def` is on line 530). Every invocation of this function counts, regardless of which schema instance or caller (top-level `dump`/`dumps`, or recursive invocations reached through `Nested` fields, or the function's own recursive call for collections) triggered it. Line numbers below are absolute, 1-based line numbers of that file as it exists in the repository.

Candidate invariants. Each predicate is evaluated on the local variables of the target function's own frame at an "observation", where an observation is one line event on the stated line, i.e. the moment JUST BEFORE that line starts executing (so variables assigned on that very line still hold their values from earlier in the same frame, and variables assigned on earlier lines already hold their new values). Every time the line is about to execute, in any invocation, that is one observation; observations from all invocations in all 12 test methods are summed. Line 540 is the `for` statement header: it is observed once before every loop iteration AND once more when the loop finds its iterator exhausted (also after a `continue`). The predicates, verbatim:

1. `len(obj) > 0` — observed at line 538 (the `return [...]` list-comprehension line).
2. `obj is not None` — observed at line 539 (`ret = self.dict_class()`).
3. `len(ret) < 3` — observed at line 540 (the `for attr_name, field_obj in ...` line).
4. `value is not None` — observed at line 542 (`if value is missing:`).
5. `attr_name.islower()` — observed at line 543 (`continue`).
6. `key == attr_name` — observed at line 545 (`ret[key] = value`).
7. `type(value) is str` — observed at line 545 (`ret[key] = value`).

For each predicate report one object with keys:
- `predicate` (str): the predicate text exactly as written between backticks above (e.g. for a hypothetical predicate `x >= 0` the string is "x >= 0").
- `observations` (int): total number of observations of that predicate across all invocations in all 12 test methods.
- `violations` (int): how many of those observations evaluated the predicate to False.
- `held_always` (bool): true iff `observations > 0` and `violations == 0`. A predicate whose observation line is never reached is reported as `observations: 0`, `violations: 0`, `held_always: false`.

Return JSON of the form {"invariant_report": [...]} with exactly one entry per predicate (7 entries), sorted by the `predicate` string in ascending order using plain Python string comparison (code-point order; predicates are all distinct, so no tie-break is needed). Integers are JSON numbers, booleans are JSON true/false.
"""

TEMPLATE = {
    "invariant_report": [
        {"held_always": "bool", "observations": "int", "predicate": "str", "violations": "int"}
    ]
}


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_locals(raw_line):
    idx = raw_line.rfind(" locals={")
    if idx < 0:
        die(f"no locals in trace line: {raw_line[:200]}")
    return ast.literal_eval(raw_line[idx + len(" locals="):])


def literal_or_none(text):
    try:
        return True, ast.literal_eval(text)
    except Exception:
        return False, None


def is_str_repr(text):
    return text[:1] in ("'", '"')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        die(f"trace log not found: {args.trace_log}")
    if not lines:
        die("trace log is empty")

    obs = {p: 0 for p in OBS_LINE}
    viol = {p: 0 for p in OBS_LINE}
    stack = []  # per-frame state: {"locals": {...}, "keys": set()}
    n_events = 0

    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_PATH):
            continue
        if not m.group("func").endswith("." + TARGET_SUFFIX):
            continue
        n_events += 1
        event = m.group("event")
        lineno = int(m.group("line"))
        loc = parse_locals(raw)

        if event == "call":
            stack.append({"locals": dict(loc), "keys": set()})
            continue
        if not stack:
            die(f"event without call frame: {raw[:200]}")
        frame = stack[-1]
        if event == "return":
            stack.pop()
            continue
        if event != "line":
            continue
        frame["locals"].update(loc)
        L = frame["locals"]

        def record(pred, ok):
            obs[pred] += 1
            if not ok:
                viol[pred] += 1

        if lineno == 538:
            record(P_LEN_OBJ, L["obj"] not in ("[]", "()"))
        elif lineno == 539:
            record(P_OBJ_NN, L["obj"] != "None")
        elif lineno == 540:
            record(P_LEN_RET, len(frame["keys"]) < 3)
        elif lineno == 542:
            record(P_NOT_NONE, L["value"] != "None")
        elif lineno == 543:
            ok, name = literal_or_none(L["attr_name"])
            if not ok:
                die("cannot decode attr_name")
            record(P_ISLOWER, name.islower())
        elif lineno == 545:
            okk, key = literal_or_none(L["key"])
            oka, attr = literal_or_none(L["attr_name"])
            if not (okk and oka):
                die("cannot decode key/attr_name")
            record(P_KEY_EQ, key == attr)
            record(P_IS_STR, is_str_repr(L["value"]))
            frame["keys"].add(key)

    if n_events == 0:
        die("zero trace events for target function")
    if stack:
        die(f"{len(stack)} unterminated frames in trace")

    report = [
        {
            "held_always": obs[p] > 0 and viol[p] == 0,
            "observations": obs[p],
            "predicate": p,
            "violations": viol[p],
        }
        for p in sorted(OBS_LINE)
    ]
    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": {"invariant_report": report},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
