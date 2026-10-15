#!/usr/bin/env python
"""Parse the decorators.py trace into the oracle for decorators_validates_schema_s6_calls."""

import argparse
import json
import re
import sys

REL_FILE = "src/marshmallow/decorators.py"
MODULE = "marshmallow.decorators"
TRACKED = [
    MODULE + ".validates_schema",
    MODULE + ".set_hook",
    MODULE + ".validates",
    MODULE + ".pre_load",
    MODULE + ".post_load",
]
TARGET = MODULE + ".validates_schema"

EVENT_RE = re.compile(r"(\S+):(\d+) (\S+) event=(\w+)")

TEST_PATH = "marshmallow_qa/decorators_validates_schema_s6_calls/files/testcase.py"
TEST_ID = TEST_PATH + "::ValidatesSchemaDecorationTest::test_decorate_pool"

QUESTION = f"""Test: `{TEST_PATH}`, test class `ValidatesSchemaDecorationTest`, single test method `test_decorate_pool` (pytest id `{TEST_ID}`), run with pytest from the repository root under the container's CPython 3.11 interpreter.

Target function: `validates_schema` defined in `src/marshmallow/decorators.py` (module imported as `marshmallow.decorators`; dotted name `marshmallow.decorators.validates_schema`). The test calls it directly, both as a plain decorator and as a decorator factory, and it also runs implicitly when the `Probe` schema class at the end of the test is defined.

Tracked set (all defined in `src/marshmallow/decorators.py`): `marshmallow.decorators.validates_schema`, `marshmallow.decorators.set_hook`, `marshmallow.decorators.validates`, `marshmallow.decorators.pre_load`, `marshmallow.decorators.post_load`.

Question: what is the exact chronological sequence of calls to tracked functions during the whole execution of the test method `test_decorate_pool` (from its first line until it returns; setUp/tearDown/fixtures contribute nothing)?

Inclusion rules:
- One element per function entry (one new Python frame of a tracked function starting to execute, i.e. one `call` event of `sys.settrace`), in the order the frames are entered.
- Every entry counts, regardless of who makes the call: calls made directly by the test code, calls made from inside another tracked function (e.g. `validates_schema` calling `set_hook`), and calls made later through the `functools.partial` objects returned by `set_hook` when it is used as a decorator factory (calling such a partial enters `set_hook` again and counts as a `set_hook` entry at the moment the partial is called).
- Repeated calls are all kept (no deduplication). None of the tracked functions are generators, so there are no resumptions.
- Calls to any function outside the tracked set (e.g. `functools.partial` itself, `defaultdict`, `random` methods, the test's own helper functions, the decorated `hook_*` functions, or any marshmallow code outside the five functions listed, such as Schema class-creation or `load` machinery) are not included, but tracked functions they call would be (should any occur).

Answer format: a JSON object `{{"function_call_order": [...]}}` where each element is `{{"file": "src/marshmallow/decorators.py", "func": "<dotted module.qualname>"}}`. `file` is the repo-relative path; `func` is the dotted `module.qualname` of the entered function, e.g. `marshmallow.decorators.pre_dump` (so always one of the five tracked names above). Elements are in chronological call order.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log not found: {args.trace_log}")
    if not lines:
        sys.exit("ERROR: trace log is empty")

    calls = []
    target_events = 0
    for raw in lines:
        m = EVENT_RE.search(raw)
        if not m:
            continue
        path, _lineno, func, event = m.groups()
        if not path.replace("\\", "/").endswith(REL_FILE):
            continue
        if func == TARGET:
            target_events += 1
        if event == "call" and func in TRACKED:
            calls.append({"file": REL_FILE, "func": func})

    if target_events == 0:
        sys.exit("ERROR: no trace events for target validates_schema")
    if not calls:
        sys.exit("ERROR: no call events for tracked functions")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": calls},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"calls={len(calls)} target_events={target_events}")


if __name__ == "__main__":
    main()
