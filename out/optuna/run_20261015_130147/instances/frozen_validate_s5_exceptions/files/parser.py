#!/usr/bin/env python
"""Derive the S5_Exceptions oracle for FrozenTrial._validate from the trace log."""
import argparse
import ast
import builtins
import json
import re
import sys

TARGET_FUNC = "optuna.trial._frozen.FrozenTrial._validate"
TARGET_FILE = "optuna/trial/_frozen.py"

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r" exc=(?P<tname>[A-Za-z_][\w]*): (?P<repr>.*) locals=\{.*\}$")

QUESTION = (
    "Consider the pytest test "
    "`optuna_qa/frozen_validate_s5_exceptions/files/testcase.py::TestFrozenTrialCreation::"
    "test_create_trials_until_invalid` (test class `TestFrozenTrialCreation`, its only test "
    "method `test_create_trials_until_invalid`). During this test run, the method "
    "`optuna.trial._frozen.FrozenTrial._validate` (defined in `optuna/trial/_frozen.py`) is "
    "invoked (indirectly, via `optuna.trial.create_trial`) several times; an invocation is one "
    "call of the method, counted 1-based in chronological order. Exactly one of these "
    "invocations does not return normally: an exception propagates out of `_validate` to its "
    "caller (the exception may be raised directly by a `raise` statement in `_validate` or by a "
    "callee and propagated through it). Report that exception. "
    "`exception_type` must be the exception class name using this convention: bare "
    "`type(exc).__name__` for built-in exceptions (e.g. `KeyError`, never `builtins.KeyError`), "
    "and `module.QualName` (i.e. `type(exc).__module__ + '.' + type(exc).__qualname__`, e.g. "
    "`optuna.exceptions.TrialPruned`) for all non-built-in exceptions. `exception_message` must "
    "be exactly `str(exc)` of that exception object, character for character (including any "
    "floating-point digits exactly as Python formats them, quotes, punctuation and the "
    "trailing period if present). Answer as a JSON object with exactly the keys "
    "`exception_message` (string) and `exception_type` (string)."
)


def type_name(name):
    if isinstance(getattr(builtins, name, None), type) and issubclass(
        getattr(builtins, name), BaseException
    ):
        return name
    raise SystemExit(f"ERROR: non-builtin exception {name!r} needs module qualification")


def parse_message(tname, rep):
    if rep.endswith("..."):
        raise SystemExit("ERROR: exception repr truncated in trace")
    if not rep.startswith(tname + "("):
        raise SystemExit(f"ERROR: unexpected exception repr: {rep!r}")
    args = ast.literal_eval(rep[len(tname):])
    if not isinstance(args, tuple):
        args = (args,)
    if len(args) == 0:
        return ""
    if len(args) == 1:
        return str(args[0])
    return str(args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        with open(a.trace_log, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        sys.exit(f"ERROR: trace log missing: {a.trace_log}")
    if not lines:
        sys.exit("ERROR: trace log empty")

    events = []
    for ln in lines:
        m = LINE_RE.match(ln)
        if not m or m.group("func") != TARGET_FUNC or not m.group("file").endswith(TARGET_FILE):
            continue
        events.append(m)
    if not events:
        sys.exit("ERROR: zero events for target function")

    # Walk invocations; an exception event followed by a return with retval=None
    # (and no further line events in that frame) means the exception propagated out.
    invocations = []
    cur = None
    for m in events:
        ev = m.group("event")
        if ev == "call":
            cur = {"exc": None, "propagated": False}
            invocations.append(cur)
        elif ev == "exception":
            em = EXC_RE.search(m.group("rest"))
            if not em:
                sys.exit(f"ERROR: unparsable exception event: {m.group(0)}")
            cur["exc"] = (em.group("tname"), em.group("repr"))
        elif ev == "line":
            # execution continued after an exception -> it was handled
            if cur is not None:
                cur["exc"] = None
        elif ev == "return":
            if cur["exc"] is not None and "retval=None" in m.group("rest"):
                cur["propagated"] = True
                cur["final"] = cur["exc"]
    propagated = [inv for inv in invocations if inv["propagated"]]
    if len(propagated) != 1:
        sys.exit(f"ERROR: expected exactly one propagating invocation, got {len(propagated)}")
    tname, rep = propagated[0]["final"]
    answer = {
        "exception_message": parse_message(tname, rep),
        "exception_type": type_name(tname),
    }
    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": answer,
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    print(f"invocations={len(invocations)} target_events={len(events)}")


if __name__ == "__main__":
    main()
