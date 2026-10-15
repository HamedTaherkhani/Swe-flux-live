#!/usr/bin/env python
"""Parse the _run_trial trace into per-exception-type observation counts."""

import argparse
import builtins
import importlib
import json
import re
import sys


TARGET_FILE = "optuna/study/_optimize.py"
TARGET_QUALNAME = "optuna.study._optimize._run_trial"
TEST_FILE = "optuna_qa/optimize_run_trial_m5_exceptions/files/testcase.py"
TEST_CLASS = "TestRunTrialExceptionMix"

# Modules searched (in order) to qualify non-builtin exception class names.
CANDIDATE_MODULES = ["optuna.exceptions", "optuna.storages._rdb.storage"]

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)
EXC_RE = re.compile(r"^ exc=(?P<name>[A-Za-z_][A-Za-z0-9_]*): ")

QUESTION = f"""\
Consider the pytest test class `{TEST_CLASS}` in `{TEST_FILE}`. Run ALL test methods of this \
class (the whole class, e.g. `pytest {TEST_FILE}::{TEST_CLASS}`), and consider the function \
`{TARGET_QUALNAME}` defined in `{TARGET_FILE}` (it is reached indirectly via \
`optuna.study.Study.optimize`).

Count how many times exceptions of each type are OBSERVED in the frame of `_run_trial`, \
aggregated over the whole run: over every invocation of `_run_trial` (an invocation is one call \
of the function) and over every test method of the class.

Observation rule: an exception is observed in the `_run_trial` frame each time either (a) a \
statement executing in that frame raises it (including an explicit `raise <expr>` statement and \
a failing `assert`), or (b) it propagates into that frame out of a call made from that frame \
(e.g. an exception escaping `func(trial)`, `study.ask()` or `_tell_with_warning(...)`; it does \
not matter how deep in the callee it was originally raised). Each such event counts once. An \
explicit `raise <expr>` that raises an exception object that was already observed earlier in the \
same frame counts AGAIN as a new observation. A bare `raise` statement (re-raising the exception \
currently being handled, with no operand) does NOT count again. Exceptions raised and fully \
handled inside a callee (never escaping into `_run_trial`) are NOT observed. Being caught by an \
`except` clause of `_run_trial` does not undo an observation. Only the `_run_trial` frame itself \
matters; observations in other frames are ignored.

Exception type naming: use the bare `type(exc).__name__` for built-in exception classes (e.g. \
`OSError`, never `builtins.OSError`), and `type(exc).__module__ + "." + \
type(exc).__qualname__` for all other classes (e.g. `optuna.exceptions.DuplicatedStudyError`).

Answer format: a JSON object with a single key `exception_type_counts` whose value is a list of \
objects `{{"exception_type": <str>, "count": <int>}}`, one object per distinct exception type \
observed at least once (types never observed are omitted; no zero counts). `count` is the total \
number of observations of that type (totals over all invocations and all test methods, not the \
number of distinct invocations or tests). Sort the list by `exception_type` ascending using plain \
Python string ordering (code-point order); exception_type values are unique so no further \
tie-break is needed.
"""


def qualify(name):
    obj = getattr(builtins, name, None)
    if isinstance(obj, type) and issubclass(obj, BaseException):
        return name
    for modname in CANDIDATE_MODULES:
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        cls = getattr(mod, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            return f"{cls.__module__}.{cls.__qualname__}"
    sys.exit(f"ERROR: cannot resolve module for non-builtin exception type {name!r}")


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

    n_target_events = 0
    n_calls = 0
    counts = {}
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if m.group("func") != TARGET_QUALNAME:
            continue
        n_target_events += 1
        event = m.group("event")
        if event == "call":
            n_calls += 1
        elif event == "exception":
            em = EXC_RE.match(m.group("rest"))
            if not em:
                sys.exit(f"ERROR: unparsable exception event: {line}")
            name = qualify(em.group("name"))
            counts[name] = counts.get(name, 0) + 1

    if n_target_events == 0 or n_calls == 0:
        sys.exit(f"ERROR: no events for {TARGET_QUALNAME} in trace")
    if not counts:
        sys.exit("ERROR: no exception events observed in target frame")

    answer = {
        "exception_type_counts": [
            {"count": counts[k], "exception_type": k} for k in sorted(counts)
        ]
    }
    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_type_counts": [{"count": "int", "exception_type": "str"}]},
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(answer, indent=2, sort_keys=True))
    print(f"target calls: {n_calls}, target events: {n_target_events}")


if __name__ == "__main__":
    main()
