"""Parse the sys.settrace log into oracle.json for instance
environment_setup_context_with_venv_s3_state (S3_ProgramState).

The answer is the ordered history of values taken by the local variable
``path`` during the TARGET_INVOCATION-th invocation (1-based, chronological
order of ``call`` events) of
``features.environment._setup_context_with_venv``.  One history entry is
recorded per assignment to ``path`` (the tracer logs locals that changed
since the previous event of the same frame, so every reassignment of
``path`` surfaces exactly once; the full-locals snapshot on the ``return``
event repeats the final value and is de-duplicated against it).  Values are
the repr strings of the whole list object, as captured by the tracer.
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "features/environment.py"
TARGET_FUNC = "features.environment._setup_context_with_venv"
TARGET_FUNC_NAME = "_setup_context_with_venv"
TARGET_INVOCATION = 2
TARGET_VAR = "path"
ASSIGNMENT_LINES = (64, 65, 66, 67)

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)
LOCALS_RE = re.compile(r"locals=(\{.*\})\s*$")

QUESTION = """When the pytest test
`kedro_qa/environment_setup_context_with_venv_s3_state/files/testcase.py::TestVenvContextState::test_venv_path_history`
is executed, the function `features.environment._setup_context_with_venv`
(defined in the repository file `features/environment.py`, lines 49-75) is
invoked several times indirectly: the test calls the same-module behave
hook `before_scenario` three times, each time with a scenario carrying the
module's fresh-venv tag and with a patched process environment;
`before_scenario` calls the same-module helper `_setup_minimal_env`, which
(because the environment flag it checks is set) resolves a fake kedro
installation directory via the mocked `subprocess.check_output` and calls
`_setup_context_with_venv(context, kedro_install_venv_dir)`. Each round of
the test rebuilds a synthetic PATH from a filesystem fixture it creates
under a fixed `/tmp` root, mixing plain directories, directories whose
parent holds a `pyvenv.cfg` marker, directories whose parent holds a
`conda-meta` directory, and directories whose parent holds both markers.

Invocation counting: one invocation is one entry into
`features.environment._setup_context_with_venv` (one function call) during
the test run; invocations are numbered 1-based in chronological order of
function entry.

Inside the function, the local variable `path` is assigned exactly four
times, by the assignment statements at lines 64, 65, 66 and 67 of
`features/environment.py` (line numbers are absolute and 1-based in the
file as it exists on disk in this repository). Two of those statements are
single-line list comprehensions; each such assignment counts exactly once,
at the moment the comprehension has finished evaluating and the name
`path` is rebound.

Task: report the ordered history of values taken by the local variable
`path` during the 2nd invocation of
`features.environment._setup_context_with_venv` in this test run. The
history has one entry per assignment to `path`, in execution order, and
each entry records the value of `path` immediately after that assignment
statement has completed. All four assignments are reported, in order, with
no de-duplication and no re-sorting.

Answer format: a JSON object with exactly one key, `value_history`, whose
value is a list with exactly one object per history entry, in history
order. Each object has exactly two keys: `step` (a JSON integer giving the
1-based position of the entry in the history) and `value` (a JSON string).
Every `value` string is the Python `repr()` of the whole `list` object
held by `path` at that moment: the list's elements are rendered as Python
string literals keeping their single quotes, exactly as
`repr(['a', 'b'])` produces the string `"['a', 'b']"`. No `str()` conversion,
no element-wise splitting, and no JSON-style spelling is used inside these
strings.
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_locals(raw_line):
    m = LOCALS_RE.search(raw_line)
    if not m:
        return {}
    try:
        parsed = ast.literal_eval(m.group(1))
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse locals dict: {exc}: {m.group(1)[:120]}")
    if not isinstance(parsed, dict):
        fail("locals payload is not a dict")
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")

    invocations = []  # list of lists of (lineno, event, locals-dict)
    current = None
    total_line_events = 0
    distinct_lines = set()

    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            if m.group("func") != TARGET_FUNC:
                continue
            event = m.group("event")
            lineno = int(m.group("line"))
            if event == "call":
                if current is not None:
                    invocations.append(current)
                current = []
            elif event == "line":
                if current is None:
                    fail("line event encountered before any call event")
                current.append((lineno, event, parse_locals(raw)))
                total_line_events += 1
                distinct_lines.add(lineno)
            elif event in ("return", "exception"):
                if current is None:
                    fail(f"{event} event encountered before any call event")
                current.append((lineno, event, parse_locals(raw)))
                invocations.append(current)
                current = None
    if current is not None:
        invocations.append(current)

    if not invocations:
        fail(f"no events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")
    if len(invocations) < TARGET_INVOCATION:
        fail(
            f"only {len(invocations)} invocation(s) traced; "
            f"need invocation {TARGET_INVOCATION}"
        )

    history = []
    for lineno, event, locals_dict in invocations[TARGET_INVOCATION - 1]:
        if TARGET_VAR not in locals_dict:
            continue
        value = locals_dict[TARGET_VAR]
        if history and history[-1] == value:
            continue
        history.append(value)

    if not history:
        fail(
            f"local variable {TARGET_VAR!r} never observed in invocation "
            f"{TARGET_INVOCATION}"
        )
    if len(history) != len(ASSIGNMENT_LINES):
        fail(
            f"expected {len(ASSIGNMENT_LINES)} assignments to {TARGET_VAR!r} "
            f"(lines {ASSIGNMENT_LINES}), observed {len(history)} distinct values"
        )

    print(f"invocations traced: {len(invocations)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"history length in invocation {TARGET_INVOCATION}: {len(history)}")
    for i, value in enumerate(history, start=1):
        print(f"step {i}: {len(value)} chars, {value.count(chr(39)) // 2} elements")

    oracle_answer = {
        "value_history": [
            {"step": i, "value": value} for i, value in enumerate(history, start=1)
        ]
    }
    template_answer = {"value_history": [{"step": "int", "value": "str"}]}
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
