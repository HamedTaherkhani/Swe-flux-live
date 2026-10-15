#!/usr/bin/env python
"""Parse the _parse_rule trace into the S3_ProgramState oracle."""
import argparse
import ast
import json
import re
import sys

TARGET_SUFFIX = "werkzeug.routing.rules.Rule._parse_rule"
TARGET_FILE = "src/werkzeug/routing/rules.py"
OBS_LINE = 640
OBS_K = 24
VARIABLES = [
    "argument_weights",
    "c_args",
    "c_kwargs",
    "content",
    "convertor_number",
    "final",
    "pos",
    "static",
    "static_weights",
]
TRUNC_LIMIT = 500

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)?(?: exc=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the pytest test "
    "`werkzeug_qa/rules_parse_rule_s3_state/files/testcase.py::TestHostRuleCompilation::test_compile_host_rules` "
    "(test file `werkzeug_qa/rules_parse_rule_s3_state/files/testcase.py`, class `TestHostRuleCompilation`, "
    "single test method `test_compile_host_rules`). During this test, the generator method "
    "`werkzeug.routing.rules.Rule._parse_rule` in `src/werkzeug/routing/rules.py` is executed many times "
    "(for host rules and path rules alike). Line 640 of that file (absolute, 1-based line number in the repository "
    "as checked out) is the statement `argument_weights.append(convobj.weight)` inside the "
    "`if data[\"variable\"] is not None:` branch. "
    "Count every execution of line 640 across the whole test run, over all `_parse_rule` generator frames "
    "(each Rule's host pattern and path pattern are parsed by separate generator objects), in "
    "chronological order, starting from 1. Observe the local variables of the `_parse_rule` frame that is executing "
    "it immediately after line 640 has finished executing for the 24th time (i.e. after that `append` call has "
    "completed, before line 641 runs). Report the values of these local variables at that moment: "
    "`argument_weights`, `c_args`, `c_kwargs`, `content`, `convertor_number`, `final`, `pos`, `static`, "
    "`static_weights`. Each value is the Python `repr()` of the variable's current value, given as a JSON string "
    "(for containers, the `repr` of the whole container, e.g. a list of tuples looks like `[(7, -1)]` and a dict like "
    "`{'k': 9}`; strings keep their surrounding single quotes and backslashes appear exactly as `repr` renders them, "
    "e.g. the 2-character string backslash+Z has repr `'\\\\Z'`; booleans are `True`/`False`). "
    "Answer with `{\"observed_state\": [{\"value\": <repr string>, \"variable\": <variable name>}, ...]}`, with one "
    "entry per listed variable, sorted by variable name ascending (the order listed above)."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log missing: {args.trace_log}")
    if not raw:
        fail("trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        if not m.group("func").endswith(TARGET_SUFFIX):
            continue
        events.append(
            (int(m.group("lineno")), m.group("event"), ast.literal_eval(m.group("locals")))
        )
    if not events:
        fail("no events for Rule._parse_rule in trace")

    # The generator is consumed eagerly, so its events are contiguous. On each
    # 'call' (start or resumption) the tracer logs the full locals; line events
    # log only changed locals, so accumulate.
    state = {}
    count = 0
    snapshot = None
    pending = False
    for lineno, event, loc in events:
        if event == "call":
            state = dict(loc)
        else:
            state.update(loc)
        if pending:
            if event != "line":
                fail(f"unexpected event {event} after observation line")
            snapshot = dict(state)
            break
        if event == "line" and lineno == OBS_LINE:
            count += 1
            if count == OBS_K:
                pending = True
    if snapshot is None:
        fail(f"line {OBS_LINE} executed only {count} times; need {OBS_K}")

    observed = []
    for var in sorted(VARIABLES):
        if var not in snapshot:
            fail(f"variable {var} not in locals at observation point")
        val = snapshot[var]
        if len(val) > TRUNC_LIMIT:
            fail(f"repr of {var} truncated by tracer")
        observed.append({"value": val, "variable": var})

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": observed},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
