#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/tree.py"
TARGET_FUNC = "lark.tree.Tree.scan_values"
TEST_FILE = "lark_qa/tree_scan_values_m2_loops/files/testcase.py"
TEST_CLASS = "TestTreeFindTokenLoopDynamics"


def fail(message):
    raise RuntimeError(message)


def locate_loop(root):
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail("target source is missing: %s" % source_path)

    module = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    tree_class = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "Tree"
        ),
        None,
    )
    if tree_class is None:
        fail("could not locate class Tree in %s" % source_path)
    function = next(
        (
            node
            for node in tree_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "scan_values"
        ),
        None,
    )
    if function is None:
        fail("could not locate Tree.scan_values in %s" % source_path)
    loop = next((node for node in function.body if isinstance(node, ast.For)), None)
    if loop is None or not loop.body:
        fail("could not locate the outer for-loop in Tree.scan_values")
    return loop.lineno, loop.body[0].lineno


def parse_locals(raw_line):
    marker = " locals="
    if marker not in raw_line:
        fail("target call event has no locals mapping")
    text = raw_line.split(marker, 1)[1]
    try:
        values = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        fail("could not parse target call locals: %s" % exc)
    if not isinstance(values, dict) or "self" not in values:
        fail("target call event does not identify self")
    if not isinstance(values["self"], str):
        fail("target call self representation is not a string")
    return values["self"]


def parse_trace(trace_path, loop_body_line):
    if not trace_path.is_file():
        fail("trace log is missing: %s" % trace_path)
    if trace_path.stat().st_size == 0:
        fail("trace log is empty: %s" % trace_path)

    event_re = re.compile(
        r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
        r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    )
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_re.search(raw_line)
        if not match:
            continue
        filename = match.group("file").replace("\\", "/")
        if not filename.endswith("/" + TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        events.append(
            (
                match.group("event"),
                int(match.group("line")),
                raw_line,
            )
        )

    if not events:
        fail("trace contains zero events for %s" % TARGET_FUNC)
    if not any(event == "call" for event, _, _ in events):
        fail("trace contains no call event for %s" % TARGET_FUNC)

    frame_segments = []
    iteration_counts = {}
    for event, line, raw_line in events:
        if event == "call":
            self_repr = parse_locals(raw_line)
            frame_segments.append(self_repr)
            iteration_counts.setdefault(self_repr, 0)
        elif event == "line" and line == loop_body_line:
            if not frame_segments:
                fail("loop body event occurred outside a target frame segment")
            iteration_counts[frame_segments[-1]] += 1
        elif event == "return":
            if not frame_segments:
                fail("target return event has no matching call segment")
            frame_segments.pop()

    if frame_segments:
        fail("trace ended with unfinished target frame segments")
    if not iteration_counts:
        fail("trace contains no logical target invocations")
    counts = list(iteration_counts.values())
    if not any(count > 0 for count in counts):
        fail("the selected loop body never executed")
    if len(set(counts)) < 6:
        fail("fewer than six distinct per-invocation loop counts were observed")

    return {
        "max_iterations": max(counts),
        "min_iterations": min(counts),
    }


def build_question(loop_line, loop_body_line):
    return (
        f"Run every pytest test method whose name begins with `test_` in class "
        f"`{TEST_CLASS}` from `{TEST_FILE}` (equivalently, select "
        f"`{TEST_FILE}::{TEST_CLASS}`), and aggregate over ALL collected methods in that "
        "class. Each method is identified by its full pytest id "
        f"`{TEST_FILE}::{TEST_CLASS}::method_name`; use pytest's collected execution order "
        "for the methods, and chronological execution order within each method. During that "
        f"complete run, consider every logical invocation of `{TARGET_FUNC}` in "
        f"`{TARGET_FILE}`, including recursive invocations. Because this function is a "
        "generator, one logical invocation means one generator object produced by evaluating "
        "one call to the function; later resumptions of that same suspended generator remain "
        "part of the same invocation and do not start another. Number invocations 1-based by "
        "the chronological order in which each generator first enters its function body. "
        f"For each invocation, count iterations of the outer `for` loop whose header is at "
        f"absolute, 1-based source line {loop_line}. Define iteration N (also 1-based) as the "
        f"Nth execution of that loop body's first statement, at line {loop_body_line}, by "
        "that invocation's own generator frame over its entire lifetime, including across "
        "yield suspensions and resumptions. An invocation whose loop body never executes has "
        "iteration count 0. Count only executions in that specific frame; exclude recursive "
        "generator frames, predicate calls, comprehensions, and every other callee or frame "
        "from that invocation's count (their own `Tree.scan_values` frames are counted as "
        "separate invocations). Source line numbers refer to the named repository file as it "
        "exists for this run. For a multi-line statement or expression, execution is "
        "attributed to the absolute line where that statement or expression begins. The "
        "function's `def` line, decorator lines, and docstring lines are not loop iterations. "
        "Retain every invocation's count, including duplicate counts; do not deduplicate or "
        "sort before computing the extrema. Compute the maximum and minimum over all retained "
        "per-invocation counts from all test methods. Return exactly one JSON object with keys "
        "`max_iterations` and `min_iterations`, in that order. Both values are JSON integers "
        "(not strings); emit no additional keys and apply no string or `repr()` formatting."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    loop_line, loop_body_line = locate_loop(root)
    answer = parse_trace(Path(args.trace_log), loop_body_line)
    payload = {
        "question_kind": "M2_Loops",
        "question": build_question(loop_line, loop_body_line),
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise
