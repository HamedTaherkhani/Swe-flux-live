#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "haystack.core.pipeline.base.PipelineBase._merge_super_component_pipelines"
TRACE_FUNC = "haystack.core.pipeline.base._merge_super_component_pipelines"
TARGET_FILE_SUFFIX = "/haystack/core/pipeline/base.py"
LOOP_BODY_FIRST_LINE = 1370
TESTCASE_PATH = Path(
    "haystack_qa/base_merge_super_component_pipelines_m2_loops/files/testcase.py"
)

QUESTION = (
    "Run every test method defined on TestMergeSuperComponentLoops in "
    "haystack_qa/base_merge_super_component_pipelines_m2_loops/files/testcase.py, as one pytest run, and aggregate "
    "over all of those methods. During that run, consider every invocation of "
    "haystack.core.pipeline.base.PipelineBase._merge_super_component_pipelines in "
    "haystack/core/pipeline/base.py. An invocation is one call of that exact function, numbered 1-based in actual "
    "chronological execution order across the full run; do not reorder or deduplicate invocations. For the for-loop "
    "whose header is line 1369 (`for socket_name, socket in entry_point_sockets.items():`), compute one iteration "
    "count per target invocation. An iteration is one execution, in the target function's own frame, of the loop "
    "body's first executable line 1370, where the `if` statement begins. Sum those executions across every activation "
    "of this loop caused by all surrounding loops within that same target invocation; if its body never executes, "
    "the invocation's count is 0. Ignore events from nested comprehension frames or any function other than the exact "
    "target function. Line numbers are absolute 1-based source lines in the named repository file as it exists for "
    "this run. For a multi-line statement, its executed line is the line where that statement or expression begins; "
    "decorator, `def`, and docstring lines do not count unless Python actually executes them in the target invocation "
    "(none is an iteration unless it is line 1370). Return exactly a JSON object with keys `max_iterations` then "
    "`min_iterations`, each containing a JSON integer: respectively the maximum and minimum of the per-invocation "
    "counts. The extrema retain duplicate counts naturally; there is no sorting or deduplication step and no string "
    "formatting or null representation is involved."
)

EVENT_RE = re.compile(
    r"\s(?P<file>\S+):(?P<line>\d+)\s+(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def expected_test_count():
    if not TESTCASE_PATH.is_file():
        fail(f"testcase source is missing: {TESTCASE_PATH}")
    tree = ast.parse(TESTCASE_PATH.read_text(encoding="utf-8"), filename=str(TESTCASE_PATH))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TestMergeSuperComponentLoops":
            methods = [
                item.name
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_")
            ]
            if not methods:
                fail("TestMergeSuperComponentLoops defines no test methods")
            return len(methods)
    fail("TestMergeSuperComponentLoops was not found")


def parse_counts(trace_path):
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    counts = []
    active_count = None

    for raw_line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX):
            continue
        if match.group("func") != TRACE_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            if active_count is not None:
                fail("encountered an overlapping target invocation")
            active_count = 0
        elif event == "line" and line == LOOP_BODY_FIRST_LINE:
            if active_count is None:
                fail("encountered a loop-body event outside a target invocation")
            active_count += 1
        elif event == "return":
            if active_count is None:
                fail("encountered a target return without a matching call")
            counts.append(active_count)
            active_count = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active_count is not None:
        fail("trace ended during a target invocation")
    if not counts:
        fail("trace contains no completed target invocations")

    wanted = expected_test_count()
    if len(counts) != wanted:
        fail(f"expected one target invocation for each of {wanted} tests, found {len(counts)}")
    if len(set(counts)) < 6:
        fail(f"loop scenario is insufficiently varied: only {len(set(counts))} distinct counts")
    return counts


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    counts = parse_counts(args.trace_log)
    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {
            "max_iterations": max(counts),
            "min_iterations": min(counts),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
