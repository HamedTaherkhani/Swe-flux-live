"""Parse the sys.settrace log into oracle.json for instance
core_load_obj_s5_exceptions (S5_Exceptions).

The answer is the deduplicated, sorted set of distinct exception type names
that were raised inside the try blocks of kedro.io.core._load_obj and caught
by that function's own except clauses, aggregated over every invocation of
the function during the test run.

Trace mechanics used: within one invocation (from a `call` event to the
terminating `return` event, or to the last event if the frame unwinds via an
exception), every `exception` event records an exception that was pending in
the function's own frame. If the invocation ends with a `return` event, all
of its exceptions were caught by the function's handlers. If the invocation
ends with an `exception` event (no `return`), that final exception
propagated out of the function and is not counted; all earlier ones were
caught and execution continued.
"""

import argparse
import json
import os
import re
import sys

TARGET_FUNC = "kedro.io.core._load_obj"

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)
EXC_RE = re.compile(r"\bevent=exception exc=(?P<etype>[A-Za-z_][A-Za-z0-9_]*):")

QUESTION = """When the pytest test
`kedro_qa/core_load_obj_s5_exceptions/files/testcase.py::TestLoadObjExceptionsRuntime::test_traced_run`
is executed, the function `kedro.io.core._load_obj` (defined in the
repository file `kedro/io/core.py`) is invoked many times indirectly,
through the call chain `kedro.io.core.AbstractDataset.from_config` ->
`kedro.io.core.parse_dataset_definition` -> `kedro.io.core._load_obj`, once
per candidate class path tried for each dataset type in the test's
programmatically built list.

Scope: consider ALL invocations of `kedro.io.core._load_obj` during the
entire test run. One invocation means one entry into the function (one call
of the function); invocations are taken in chronological order, though the
final answer does not depend on their order.

Task: report the set of distinct exception types that were raised inside the
function's `try` blocks and CAUGHT by the function's own `except` clauses,
aggregated across all invocations.

Definitions and conventions:

- An exception counts as "caught by the function" only if it was raised by
  code executed inside one of the function's own `try` blocks (including by
  functions called from those blocks, e.g. the import/attribute helper it
  calls) and was then intercepted by one of the function's own `except`
  clauses, so that execution of the function body continued after the
  interception.
- An exception that propagates out of the function is NOT counted: if an
  invocation of the function terminates by raising (rather than by
  returning), the exception with which it terminates is excluded. Exceptions
  raised by the function's own `raise` statements are therefore excluded
  unless they are themselves caught by one of the function's own `except`
  clauses.
- Exceptions raised and/or caught entirely inside other functions (callers
  or callees of the target) never count; only interception by the target
  function's own `except` clauses qualifies.
- Exception type names are reported as bare `type(exc).__name__` for
  built-in exception classes (for example `KeyError`, never
  `builtins.KeyError`) and as `module.QualName` for non-built-in exception
  classes (for example `some_package.errors.CustomError`).
- The answer is the deduplicated set of these exception type names, sorted
  in ascending lexicographic order exactly as Python's `sorted()` orders
  strings (ASCII code-point order).

Answer format: a JSON object with exactly one key, `caught_exception_kinds`,
whose value is a list of strings (the sorted, deduplicated exception type
names).
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")

    invocations = []  # each: {"events": [(event, etype_or_none), ...]}
    current = None
    total_line_events = 0
    distinct_lines = set()
    total_exception_events = 0

    def close_current():
        nonlocal current
        if current is not None:
            invocations.append(current)
            current = None

    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_FUNC:
                continue
            event = m.group("event")
            if event == "call":
                close_current()
                current = {"events": []}
            elif event == "line":
                if current is None:
                    fail("line event encountered before any call event")
                current["events"].append(("line", None))
                total_line_events += 1
                distinct_lines.add(int(m.group("line")))
            elif event == "return":
                if current is None:
                    fail("return event encountered before any call event")
                current["events"].append(("return", None))
                close_current()
            elif event == "exception":
                if current is None:
                    fail("exception event encountered before any call event")
                em = EXC_RE.search(raw)
                if not em:
                    fail(f"could not extract exception type from: {raw!r}")
                current["events"].append(("exception", em.group("etype")))
                total_exception_events += 1
    close_current()

    if not invocations:
        fail(f"no events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")
    if total_exception_events == 0:
        fail("zero exception events for target function")

    caught_kinds = set()
    for inv in invocations:
        events = inv["events"]
        exc_types = [etype for ev, etype in events if ev == "exception"]
        if events and events[-1][0] == "exception":
            # The frame unwound: the final exception propagated out of the
            # function, so it was not caught by the function itself.
            exc_types = exc_types[:-1]
        caught_kinds.update(exc_types)

    if not caught_kinds:
        fail("no caught exceptions detected in any invocation")

    answer_list = sorted(caught_kinds)

    print(f"invocations traced: {len(invocations)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"total exception events: {total_exception_events}")
    print(f"caught exception kinds: {answer_list}")

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": {"caught_exception_kinds": answer_list},
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
