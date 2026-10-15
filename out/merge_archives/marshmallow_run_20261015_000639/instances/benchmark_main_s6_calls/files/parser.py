#!/usr/bin/env python
"""Derive the S6 call-order oracle for performance.benchmark.main from a trace log."""

import argparse
import json
import re
import sys

TARGET_FILE = "performance/benchmark.py"
MODULE = "performance.benchmark"
TARGET_FUNC = f"{MODULE}.main"
INVOCATION = 2

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>/\S+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Consider the pytest test "
    "`marshmallow_qa/benchmark_main_s6_calls/files/testcase.py::TestBenchmarkMain::"
    "test_main_runs_several_configurations` (test file "
    "`marshmallow_qa/benchmark_main_s6_calls/files/testcase.py`, class `TestBenchmarkMain`, "
    "its single test method `test_main_runs_several_configurations`). The test calls the "
    "function `performance.benchmark.main` (defined in `performance/benchmark.py`) several "
    "times with different patched `sys.argv` values. Invocations of `main` are numbered 1, 2, 3, ... "
    "in chronological order of their Python `call` events during the test. "
    "Focus on invocation 2 of `main`. "
    "Report, in chronological order of their Python `call` events (as seen by `sys.settrace`), "
    "EVERY call to a function or method defined in `performance/benchmark.py` that occurs while "
    "invocation 2 of `main` is on the call stack -- i.e. transitive/nested calls count, not just "
    "calls made directly from `main`'s own frame (for example, calls that happen inside marshmallow "
    "or `timeit` code which in turn call back into functions defined in `performance/benchmark.py` "
    "are included). The tracked set is exactly these functions of `performance/benchmark.py`: "
    "`must_not_be_blank`, `AuthorSchema.get_full_name`, `QuoteSchema.add_full_name`, "
    "`Author.__init__`, `Quote.__init__`, `run_timeit`, and the `lambda` defined inside `run_timeit`. "
    "Exclude the call event of `main` itself, exclude comprehension frames (list comprehensions / "
    "generator expressions are not reported as calls, but tracked functions called from inside them "
    "ARE reported), and exclude any function not defined in `performance/benchmark.py` (marshmallow, "
    "timeit, argparse, builtins, etc.). Every call is listed separately: repeated calls to the same "
    "function each produce their own entry (no deduplication). No generator resumptions occur. "
    "Each entry is an object `{\"file\": str, \"func\": str}` where `file` is the repo-relative path "
    "`performance/benchmark.py` and `func` is the dotted name `<module>.<co_qualname>` with module "
    "`performance.benchmark`, e.g. `performance.benchmark.Author.__init__` for `Author.__init__`; "
    "the lambda in `run_timeit` is written with its Python qualname, i.e. "
    "`performance.benchmark.run_timeit.<locals>.<lambda>`. "
    "Answer as JSON: `{\"function_call_order\": [{\"file\": ..., \"func\": ...}, ...]}`."
)


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def rel_file(path):
    idx = path.find(TARGET_FILE)
    if idx < 0:
        return None
    return TARGET_FILE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log not found: {args.trace_log}")
    if not raw:
        fail("trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if rel_file(m.group("file")) is None:
            continue
        events.append((m.group("func"), m.group("event")))

    if not any(f == TARGET_FUNC and e == "call" for f, e in events):
        fail("no call events for target function in trace")

    main_calls = 0
    depth = 0
    active = False
    seq = []
    finished = False
    for func, event in events:
        if func == TARGET_FUNC:
            if event == "call":
                if depth == 0:
                    main_calls += 1
                    active = main_calls == INVOCATION
                depth += 1
            elif event == "return":
                depth -= 1
                if depth == 0 and active:
                    active = False
                    finished = True
            continue
        if not active or event != "call":
            continue
        qual = func[len(MODULE) + 1:] if func.startswith(MODULE + ".") else func
        last = qual.rsplit(".", 1)[-1]
        if last in ("<listcomp>", "<genexpr>", "<setcomp>", "<dictcomp>"):
            continue
        seq.append({"file": TARGET_FILE, "func": func})

    if main_calls < INVOCATION:
        fail(f"only {main_calls} invocations of {TARGET_FUNC} found")
    if not finished:
        fail("invocation did not return in trace")
    if not seq:
        fail("empty call sequence")

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": seq},
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"]))


if __name__ == "__main__":
    main()
