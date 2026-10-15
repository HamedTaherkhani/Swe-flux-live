"""Parse the line trace of Mapping._deserialize into oracle.json (S3_ProgramState)."""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE = "src/marshmallow/fields.py"
TARGET_FUNC = "marshmallow.fields.Mapping._deserialize"
OBS_LINE = 1723
OBS_K = 11
VARIABLES = ["deser_val", "errors", "key", "keys", "result", "val"]

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)

QUESTION = f"""\
Test: `marshmallow_qa/fields_deserialize_s3_state/files/testcase.py::MappingLoadTest::test_load_bucket_ledger` \
(test class `MappingLoadTest`, single test method `test_load_bucket_ledger`).
Target function: `marshmallow.fields.Mapping._deserialize` defined in `src/marshmallow/fields.py` \
(reached indirectly here through `fields.Dict` values nested inside a `fields.List` of a schema being loaded).

Consider every execution of the statement on line {OBS_LINE} of `src/marshmallow/fields.py` \
(`result[keys[key]] = deser_val`, inside the `else:` clause of the try statement in the value-deserialization loop), \
counted chronologically across ALL invocations of `Mapping._deserialize` during the whole test run \
(the counter is NOT reset per invocation; counting is 1-based). Line numbers are absolute and 1-based in the file as it exists in the repository.

Observation point: immediately after line {OBS_LINE} has finished executing for the {OBS_K}th time during the test run \
(i.e. the state of that same frame right before its next line executes).

At that observation point, report the values of these local variables of that `Mapping._deserialize` frame: \
`deser_val`, `errors`, `key`, `keys`, `result`, `val`.

Answer format: {{"observed_state": [{{"value": <str>, "variable": <str>}}, ...]}} with exactly one entry per variable listed above, \
sorted by `variable` name in ascending lexicographic (ASCII) order. `variable` is the bare local variable name. \
`value` is the Python `repr()` of the variable's value at that moment, given as a string; for containers it is the `repr` of the whole container \
(dicts in insertion order; a `collections.defaultdict` uses its standard repr, e.g. `defaultdict(<class 'list'>, {{'a': [1]}})`), \
so strings keep their quotes (e.g. `'abc'`), and Python spellings like `None`, `True`, `1.0` are used inside the string.\
"""


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_locals(rest):
    idx = rest.rfind("locals=")
    if idx < 0:
        die(f"no locals in trace line: {rest[:200]}")
    return ast.literal_eval(rest[idx + len("locals="):])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    events = []
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = EVENT_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
                continue
            if m.group("func") != TARGET_FUNC:
                continue
            events.append(
                (m.group("event"), int(m.group("line")), parse_locals(m.group("rest")))
            )
    if not events:
        die("zero events for target function in trace")

    stack = []  # list of [state_dict, pending_observation]
    count = 0
    observed = None
    for event, line, locs in events:
        if event == "call":
            stack.append([dict(locs), False])
            continue
        if not stack:
            die("event outside of any traced call")
        frame = stack[-1]
        frame[0].update(locs)
        if frame[1] and observed is None:
            observed = dict(frame[0])
        frame[1] = False
        if event == "line" and line == OBS_LINE:
            count += 1
            if count == OBS_K:
                frame[1] = True
        if event == "return":
            stack.pop()

    if observed is None:
        die(f"line {OBS_LINE} executed only {count} times (< {OBS_K})")

    state = []
    for var in sorted(VARIABLES):
        if var not in observed:
            die(f"variable {var} not present at observation point")
        val = observed[var]
        if val.endswith("..."):
            die(f"value of {var} appears truncated in trace")
        state.append({"value": val, "variable": var})

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": state},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    print(f"line {OBS_LINE} executions: {count}; target events: {len(events)}")


if __name__ == "__main__":
    main()
