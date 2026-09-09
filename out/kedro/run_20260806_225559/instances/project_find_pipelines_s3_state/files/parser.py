"""Parse the sys.settrace log into oracle.json for instance
project_find_pipelines_s3_state (S3_ProgramState).

The answer is the observed local state of the single invocation of
``kedro.framework.project.find_pipelines`` immediately after the assignment
statement at line ASSIGN_LINE of ``kedro/framework/project/__init__.py`` has
executed for the KTH time.

The tracer logs only the locals that changed since the previous event of the
same frame (full locals on ``call``/``return``), so the parser accumulates
every logged change into a running state. The observation point is the first
trace event of the target frame strictly after the KTH ``line`` event at
ASSIGN_LINE: at that moment the KTH execution of the assignment has fully
completed (its mutation of ``pipelines_dict`` surfaces in the accumulated
state) and no subsequent statement of the function has executed yet.
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/framework/project/__init__.py"
TARGET_FUNC = "kedro.framework.project.find_pipelines"
ASSIGN_LINE = 459
KTH = 7
VARIABLES = [
    "pipeline_name",
    "pipeline_module_name",
    "pipeline_obj",
    "pipelines_dict",
    "raise_errors",
]

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)
LOCALS_RE = re.compile(r"locals=(\{.*\})\s*$")

QUESTION = """When the pytest test
`kedro_qa/project_find_pipelines_s3_state/files/testcase.py::TestFindPipelinesProgramState::test_find_pipelines_state`
is executed, the test programmatically builds a synthetic Kedro project
package named `kedroqa_dynproj` in a fresh temporary directory, inserts that
directory at the front of `sys.path`, calls
`kedro.framework.project.configure_project` with the package name, and then
calls `kedro.framework.project.find_pipelines()` exactly once, with all
arguments left at their defaults. The generated project contains a top-level
`pipeline.py` module exposing a valid `create_pipeline` function, plus a
`pipelines/` package holding a mixture of entries created in a fixed,
seed-deterministic order: one regular file, one hidden directory (name
starting with `.`), eleven valid pipeline subpackages whose `create_pipeline`
functions build `Pipeline` objects with per-pipeline node counts derived
from a seeded formula, one subpackage that does not define
`create_pipeline`, one subpackage whose `create_pipeline` returns a plain
`dict`, and one subpackage whose source is syntactically invalid so that
importing it raises.

Target function: `kedro.framework.project.find_pipelines`, defined in the
repository file `kedro/framework/project/__init__.py` (the function body
spans lines 368-460; all line numbers below are absolute, 1-based, as the
file exists on disk in this repository).

Invocation counting: one invocation is one entry into
`kedro.framework.project.find_pipelines` (one function call) during the
test run, numbered 1-based in chronological order of function entry. In
this test run there is exactly one invocation.

During that invocation, the assignment statement at line 459
(`pipelines_dict[pipeline_name] = pipeline_obj`) executes once per
successfully discovered pipeline subpackage. Count these executions 1-based
in chronological order of execution.

Task: report the values of the following five local variables of that
invocation, observed at the moment immediately after line 459 has executed
for the 7th time — that is, after the seventh execution of that statement
has fully completed, and before any further statement of the loop (body or
loop header) executes:

1. `pipeline_name`
2. `pipeline_module_name`
3. `pipeline_obj`
4. `pipelines_dict`
5. `raise_errors`

Answer format: a JSON object with exactly one key, `observed_state`, whose
value is a list of exactly five objects, in the variable order listed
above. Each object has exactly two keys: `variable` (a JSON string holding
the variable name) and `value` (a JSON string). Every `value` is the Python
`repr()` of the corresponding variable's value at the observation moment.
For containers this is the `repr()` of the whole container: strings keep
their single quotes (so a string variable named, for illustration only,
holding abc would be reported as the 5-character string `'abc'`),
`None`/`True`/`False` use Python spelling, dictionaries appear in Python
dict-repr form with keys in insertion order, and any newline characters
inside a repr appear as real newline characters inside the JSON string. No
`str()` conversion, no truncation, and no re-sorting of any kind is
applied.
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
            if TARGET_FILE_REL not in m.group("file").replace("\\", "/"):
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
    if current is not None:
        invocations.append(current)

    if not invocations:
        fail(f"no events for target function {TARGET_FUNC} in trace log")
    if total_line_events == 0:
        fail("zero executed line events for target function")
    if len(invocations) != 1:
        fail(f"expected exactly 1 invocation, traced {len(invocations)}")

    state = {}
    armed = False
    seen_assign = 0
    snapshot = None
    for lineno, event, locals_dict in invocations[0]:
        state.update(locals_dict)
        if armed:
            snapshot = dict(state)
            break
        if event == "line" and lineno == ASSIGN_LINE:
            seen_assign += 1
            if seen_assign == KTH:
                armed = True

    total_assign = sum(
        1
        for lineno, event, _ in invocations[0]
        if event == "line" and lineno == ASSIGN_LINE
    )

    if snapshot is None:
        fail(
            f"line {ASSIGN_LINE} executed only {total_assign} time(s); "
            f"need at least {KTH}"
        )
    missing = [v for v in VARIABLES if v not in snapshot]
    if missing:
        fail(f"variables never observed at snapshot point: {missing}")
    if total_line_events < 40:
        fail(f"only {total_line_events} line events; need at least 40")
    if len(distinct_lines) < 8:
        fail(f"only {len(distinct_lines)} distinct lines; need at least 8")

    print(f"invocations traced: {len(invocations)}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"executions of line {ASSIGN_LINE}: {total_assign}")
    print(f"snapshot after execution #{KTH} of line {ASSIGN_LINE}:")
    for name in VARIABLES:
        print(f"  {name}: {len(snapshot[name])} chars")

    oracle_answer = {
        "observed_state": [
            {"value": snapshot[name], "variable": name} for name in VARIABLES
        ]
    }
    template_answer = {"observed_state": [{"value": "str", "variable": "str"}]}
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
