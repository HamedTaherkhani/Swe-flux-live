#!/usr/bin/env python
"""Derive the S5_Exceptions oracle for _is_resource_modified from the trace log."""

import argparse
import ast
import builtins
import json
import re
import sys

TARGET_SUFFIX = "werkzeug.sansio.http._is_resource_modified"
TARGET_FILE = "src/werkzeug/sansio/http.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)
EXC_RE = re.compile(r"^exc=(?P<name>[A-Za-z_][\w.]*): (?P<repr>.*) locals=\{.*\}$")
RET_RE = re.compile(r"^retval=(?P<retval>.*?) locals=\{.*\}$")

QUESTION = (
    "In the werkzeug repository, run the pytest test "
    "`werkzeug_qa/http_is_resource_modified_s5_exceptions/files/testcase.py::"
    "IsResourceModifiedBatchTest::test_conditional_batch` (test class "
    "`IsResourceModifiedBatchTest`, its single test method `test_conditional_batch`). "
    "The test calls the target function `werkzeug.sansio.http._is_resource_modified` "
    "(defined in `src/werkzeug/sansio/http.py`) once per generated request, in the "
    "order the requests are generated. An invocation is one call of that function "
    "during the test run; invocations are numbered 1-based in chronological order. "
    "Some invocations return a bool normally, while others terminate because an "
    "exception propagates out of the target function's frame to the test (whether "
    "that exception is raised by a `raise` statement in the target itself or is raised "
    "inside a function the target calls and is not handled in the target). Consider "
    "the LAST invocation, chronologically, that terminates with a propagated "
    "exception. Report that exception object as it reaches the test. "
    "`exception_type`: for a built-in exception use the bare `type(exc).__name__` "
    "(e.g. `KeyError`, never `builtins.KeyError`); for any other exception use "
    "`module.QualName` of its class (e.g. `werkzeug.exceptions.NotFound`). "
    "`exception_message`: exactly `str(exc)`, character for character (no type "
    "prefix, no added surrounding quotes). Answer as a JSON object with exactly the "
    "keys `exception_type` (string) and `exception_message` (string)."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def exc_message_from_repr(text):
    node = ast.parse(text, mode="eval").body
    if not isinstance(node, ast.Call):
        fail(f"cannot parse exception repr: {text!r}")
    args = [ast.literal_eval(a) for a in node.args]
    if node.keywords:
        fail(f"unexpected keywords in exception repr: {text!r}")
    if len(args) == 0:
        return ""
    if len(args) == 1:
        return str(args[0])
    return str(tuple(args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ns = ap.parse_args()

    try:
        with open(ns.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log missing: {ns.trace_log}")
    if not raw:
        fail("trace log is empty")

    invocations = []
    current = None
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").endswith(TARGET_FILE):
            continue
        if not m.group("func").endswith(TARGET_SUFFIX):
            continue
        event = m.group("event")
        rest = m.group("rest")
        if event == "call":
            if current is not None:
                fail("nested/unterminated invocation in trace")
            current = {"exc": None, "last_event": "call"}
            invocations.append(current)
            continue
        if current is None:
            fail(f"event outside of an invocation: {line}")
        if event == "exception":
            em = EXC_RE.match(rest)
            if not em:
                fail(f"cannot parse exception event: {line}")
            current["exc"] = (em.group("name"), em.group("repr"))
        elif event == "return":
            rm = RET_RE.match(rest)
            if not rm:
                fail(f"cannot parse return event: {line}")
            current["propagated"] = (
                current["last_event"] == "exception" and rm.group("retval") == "None"
            )
            current = None
            continue
        current["last_event"] = event

    if not invocations:
        fail("zero events for target function in trace")
    if current is not None:
        fail("last invocation never returned")

    propagated = [inv for inv in invocations if inv.get("propagated")]
    if not propagated:
        fail("no invocation propagated an exception")
    name, rep = propagated[-1]["exc"]
    if "." not in name and not (
        isinstance(getattr(builtins, name, None), type)
        and issubclass(getattr(builtins, name), BaseException)
    ):
        fail(f"non-builtin exception without module qualification: {name}")

    answer = {
        "exception_message": exc_message_from_repr(rep),
        "exception_type": name,
    }
    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": answer,
    }
    with open(ns.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    print(f"invocations={len(invocations)} propagated={len(propagated)}")


if __name__ == "__main__":
    main()
