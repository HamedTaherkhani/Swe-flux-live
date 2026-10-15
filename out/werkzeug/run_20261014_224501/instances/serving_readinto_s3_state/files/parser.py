#!/usr/bin/env python
"""Parse the DechunkedInput.readinto trace into the S3_ProgramState oracle."""
import argparse
import ast
import json
import re
import sys

TARGET_FILE = "src/werkzeug/serving.py"
TARGET_FUNC = "werkzeug.serving.DechunkedInput.readinto"
TARGET_INVOCATION = 7
VARIABLE = "read"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: retval=.*?)?(?: exc=.*?)? locals=(?P<locals>\{.*\})$"
)

QUESTION = (
    "Consider the pytest test "
    "`werkzeug_qa/serving_readinto_s3_state/files/testcase.py::TestDechunkedReadinto::test_readinto_varied_buffers` "
    "(test file `werkzeug_qa/serving_readinto_s3_state/files/testcase.py`, class `TestDechunkedReadinto`, "
    "single test method `test_readinto_varied_buffers`). During this test the method "
    "`werkzeug.serving.DechunkedInput.readinto` defined in `src/werkzeug/serving.py` is called many times. "
    "An invocation is one call of that method during the test run; invocations are numbered 1, 2, 3, ... in "
    "chronological order of their calls. Consider invocation number 7. In the body of `readinto`, the local "
    "variable `read` is assigned by exactly three statements: `read = 0`, `read = len(buf)`, and `read += n` "
    "(the augmented assignment counts as an assignment). Report the full ordered history of `read` within "
    "invocation 7: one entry per execution of any of those three assignment statements in that invocation, in "
    "the chronological order in which they executed, where the entry's value is the value `read` holds "
    "immediately after that statement has finished executing. Every execution produces an entry, even if the "
    "value equals the previous one (no deduplication); the initial `read = 0` is the first entry. "
    "`step` is the 1-based position of the entry in this history (an integer). `value` is the Python `repr()` "
    "of the integer value given as a JSON string (e.g. the integer seven is written as \"7\", not 7). "
    "Answer with `{\"value_history\": [{\"step\": <int>, \"value\": <repr string>}, ...]}`, sorted by `step` "
    "ascending."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def assign_lines():
    with open(TARGET_FILE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DechunkedInput":
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "readinto":
                    lines = set()
                    for sub in ast.walk(fn):
                        if isinstance(sub, ast.Assign) and any(
                            isinstance(t, ast.Name) and t.id == VARIABLE for t in sub.targets
                        ):
                            lines.add(sub.lineno)
                        elif (
                            isinstance(sub, ast.AugAssign)
                            and isinstance(sub.target, ast.Name)
                            and sub.target.id == VARIABLE
                        ):
                            lines.add(sub.lineno)
                    return lines
    fail("could not locate DechunkedInput.readinto in source")


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

    targets = assign_lines()
    if len(targets) != 3:
        fail(f"expected 3 assignment lines for {VARIABLE}, found {sorted(targets)}")

    invocations = []
    current = None
    for line in raw:
        m = LINE_RE.match(line)
        if not m or not m.group("file").endswith(TARGET_FILE) or m.group("func") != TARGET_FUNC:
            continue
        event = m.group("event")
        lineno = int(m.group("lineno"))
        locs = ast.literal_eval(m.group("locals"))
        if event == "call":
            current = {"state": dict(locs), "events": []}
            invocations.append(current)
            continue
        if current is None:
            fail("event outside of an invocation")
        current["state"].update(locs)
        current["events"].append((event, lineno, current["state"].get(VARIABLE)))
        if event == "return":
            current = None

    if not invocations:
        fail("no events for target function in trace")
    if len(invocations) < TARGET_INVOCATION:
        fail(f"only {len(invocations)} invocations traced")

    evs = invocations[TARGET_INVOCATION - 1]["events"]
    history = []
    for i, (event, lineno, _val) in enumerate(evs):
        if event == "line" and lineno in targets:
            if i + 1 >= len(evs):
                fail("assignment with no following event")
            val = evs[i + 1][2]
            if val is None:
                fail("read not bound after assignment")
            history.append(val)
    if len(history) < 8:
        fail(f"history too short: {history}")

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"value_history": [{"step": "int", "value": "str"}]},
        "oracle_answer": {
            "value_history": [{"step": i + 1, "value": v} for i, v in enumerate(history)]
        },
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
