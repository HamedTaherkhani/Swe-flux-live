"""Parse the sys.settrace log into oracle.json for instance
pipeline_validate_inputs_outputs_m5_exceptions (M5_Exceptions).

The answer is a crash matrix over the test methods of
TestValidateInputsOutputsCrashMatrix: which methods make the pipeline
construction raise out of kedro.pipeline.pipeline._validate_inputs_outputs
(and with what exception type) vs which complete safely.

Trace mechanics used: the shared conftest enables the tracer at each test's
setup and disables it at teardown, and every enable() emits a
"[TRACE][START]" marker line, so the trace log is a chronological sequence
of per-test blocks. The pytest progress output (pytest -rA -s) lists the
executed test ids in the same chronological order, so blocks are zipped
with test ids one-to-one. The scenario guarantees exactly one invocation of
the target per test method; an invocation that terminates with an
exception event (no return) corresponds to a crashing test, an invocation
that returns corresponds to a safe test.

Exception type names from the trace (bare `exc_type.__name__`) are resolved
to the reporting convention: bare name for built-in exception classes,
`module.QualName` otherwise, by looking the class up in the target module
(and falling back to builtins).
"""

import argparse
import builtins
import importlib
import inspect
import json
import os
import re
import sys

TARGET_FUNC = "kedro.pipeline.pipeline._validate_inputs_outputs"
TARGET_MODULE = "kedro.pipeline.pipeline"

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)
EXC_RE = re.compile(r"\bevent=exception exc=(?P<etype>[A-Za-z_][A-Za-z0-9_]*):")
START_RE = re.compile(r"\[TRACE\]\[START\]")
OUTCOMES = "PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS"
# Multi-file progress lines: "<id> PASSED [  7%]".
PYTEST_PROGRESS_RE = re.compile(
    rf"^(?P<tid>\S+\.py::\S+::\S+)\s+(?:{OUTCOMES})\s*\[\s*\d+%\]"
)
# Single-file runs collapse progress to dots; ids appear in the `-rA`
# short test summary in execution order: "PASSED <id>".
PYTEST_SUMMARY_RE = re.compile(rf"^(?:{OUTCOMES})\s+(?P<tid>\S+\.py::\S+::\S+)\s*$")

QUESTION = """When the pytest test class
`kedro_qa/pipeline_validate_inputs_outputs_m5_exceptions/files/testcase.py::TestValidateInputsOutputsCrashMatrix`
is executed by pytest, each of its 14 test methods (`test_case_00` through
`test_case_13`, which pytest runs in alphabetical order) programmatically
builds a Kedro chain pipeline and then calls the public helper
`kedro.pipeline.pipeline.pipeline(...)` exactly once with method-specific
`inputs`/`outputs`/`namespace` arguments. This drives the target function
`kedro.pipeline.pipeline._validate_inputs_outputs` (defined in the
repository file `kedro/pipeline/pipeline.py`) through the call chain
`pipeline()` -> `Pipeline.__init__` -> `Pipeline._map_nodes` ->
`_validate_inputs_outputs`, with exactly one invocation of the target per
test method.

Task: determine, for each of the 14 test methods, whether the `pipeline(...)`
call raises an exception out of `_validate_inputs_outputs` ("crashes") or
completes without raising ("safe"), and for each crashing method determine
the type of the exception that propagates out of the target function.

Definitions and conventions:

- "Crash" means the `pipeline(...)` expression in the test raises an
  exception whose failing `raise` statement sits inside
  `_validate_inputs_outputs` itself; the exception propagates through
  `Pipeline._map_nodes` and `Pipeline.__init__` back into the test method,
  which anticipates it, so every test method still PASSES under pytest.
  "Safe" means the `pipeline(...)` call returns a `Pipeline` normally.
- Every test method is constructed so that the dataset-existence check that
  `Pipeline._map_nodes` performs immediately before calling
  `_validate_inputs_outputs` always succeeds; hence the target is invoked
  exactly once per test method and the crash, when it happens, is decided
  inside the target function.
- Test methods are referenced by their full pytest id strings, of the form
  `<repo-relative-file-path>::<TestClassName>::<test_method_name>`, for
  example
  `kedro_qa/pipeline_validate_inputs_outputs_m5_exceptions/files/testcase.py::TestValidateInputsOutputsCrashMatrix::test_case_99`.
- Exception type names are reported as bare `type(exc).__name__` for
  built-in exception classes (for example `ValueError`, never
  `builtins.ValueError`) and as `module.QualName` for all other exception
  classes (for example `some_package.errors.CustomError`).
- Both lists are sorted in ascending lexicographic order by test id exactly
  as Python's `sorted()` orders strings (ASCII code-point order). Each test
  id appears at most once in the whole answer (a test is either crashing or
  safe, never both); no duplicates.

Answer format: a JSON object with exactly two keys:
- `crashing_tests`: a list of objects, one per crashing test, each object
  having exactly the keys `exception_type` (a string, the exception type
  name per the convention above) and `test` (a string, the pytest id).
- `safe_tests`: a list of strings (the pytest ids of the safe tests).
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_type_name(bare: str) -> str:
    cls = None
    try:
        mod = importlib.import_module(TARGET_MODULE)
        cls = getattr(mod, bare, None)
    except Exception:
        cls = None
    if not (inspect.isclass(cls) and issubclass(cls, BaseException)):
        cls = getattr(builtins, bare, None)
    if not (inspect.isclass(cls) and issubclass(cls, BaseException)):
        fail(f"could not resolve exception class for bare name {bare!r}")
    if cls.__module__ == "builtins":
        return cls.__name__
    return f"{cls.__module__}.{cls.__qualname__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--pytest-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    for path in (args.trace_log, args.pytest_log):
        if not os.path.isfile(path):
            fail(f"log not found: {path}")
        if os.path.getsize(path) == 0:
            fail(f"log is empty: {path}")

    test_ids = []
    with open(args.pytest_log, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            m = PYTEST_PROGRESS_RE.match(line) or PYTEST_SUMMARY_RE.match(line)
            if m:
                test_ids.append(m.group("tid"))
    if not test_ids:
        fail(f"no pytest progress test ids found in {args.pytest_log}")

    blocks = []  # each: list of (event, lineno, etype_or_none) for target
    current = None
    total_line_events = 0
    distinct_lines = set()
    total_exception_events = 0

    with open(args.trace_log, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if START_RE.search(raw):
                current = []
                blocks.append(current)
                continue
            m = LINE_RE.match(raw)
            if not m or m.group("func") != TARGET_FUNC:
                continue
            if current is None:
                fail("target event encountered before any [TRACE][START] marker")
            event = m.group("event")
            if event == "line":
                current.append(("line", int(m.group("line")), None))
                total_line_events += 1
                distinct_lines.add(int(m.group("line")))
            elif event == "call":
                current.append(("call", int(m.group("line")), None))
            elif event == "return":
                current.append(("return", int(m.group("line")), None))
            elif event == "exception":
                em = EXC_RE.search(raw)
                if not em:
                    fail(f"could not extract exception type from: {raw!r}")
                current.append(("exception", int(m.group("line")), em.group("etype")))
                total_exception_events += 1

    if not blocks:
        fail(f"no [TRACE][START] blocks found in {args.trace_log}")
    if len(blocks) != len(test_ids):
        fail(
            f"block/test mismatch: {len(blocks)} trace blocks vs "
            f"{len(test_ids)} pytest test ids"
        )
    if total_line_events == 0:
        fail("zero executed line events for target function")
    if total_exception_events == 0:
        fail("zero exception events for target function")

    crashing = []
    safe = []
    for tid, events in zip(test_ids, blocks):
        calls = [e for e in events if e[0] == "call"]
        if len(calls) != 1:
            fail(f"expected exactly 1 invocation of target for {tid}, got {len(calls)}")
        # The target has no try/except of its own, so any exception event in
        # its frame propagated out of the function. (On some interpreter
        # versions a synthetic return event with retval=None still follows
        # the exception event as the frame unwinds, so the mere presence of
        # an exception event — not the last event kind — decides the crash.)
        exc_events = [e for e in events if e[0] == "exception"]
        if exc_events:
            crashing.append(
                {"exception_type": resolve_type_name(exc_events[-1][2]), "test": tid}
            )
        elif events[-1][0] == "return":
            safe.append(tid)
        else:
            fail(f"target invocation for {tid} has no return/exception terminator")

    crashing.sort(key=lambda entry: entry["test"])
    safe.sort()

    if not crashing or not safe:
        fail("degenerate crash matrix: need both crashing and safe tests")

    print(f"tests: {len(test_ids)} (crashing={len(crashing)}, safe={len(safe)})")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"total exception events: {total_exception_events}")

    oracle = {
        "question_kind": "M5_Exceptions",
        "question": QUESTION,
        "template_answer": {
            "crashing_tests": [{"exception_type": "str", "test": "str"}],
            "safe_tests": ["str"],
        },
        "oracle_answer": {"crashing_tests": crashing, "safe_tests": safe},
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
