#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/lexer.py"
TARGET_FUNC = "lark.lexer._create_unless"
TEST_FILE = "lark_qa/lexer_create_unless_m2_loops/files/testcase.py"
TEST_CLASS = "TestCreateUnlessLoopDynamics"


def fail(message):
    raise RuntimeError(message)


def locate_loops(root):
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail("target source is missing: %s" % source_path)

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_create_unless"
        ),
        None,
    )
    if function is None:
        fail("could not locate _create_unless in %s" % source_path)

    outer = next((node for node in function.body if isinstance(node, ast.For)), None)
    if outer is None:
        fail("could not locate the outer for-loop in _create_unless")
    inner = next(
        (
            node
            for statement in outer.body
            for node in ast.walk(statement)
            if isinstance(node, ast.For)
        ),
        None,
    )
    if inner is None or not outer.body or not inner.body:
        fail("could not locate the nested for-loop bodies in _create_unless")
    return outer.lineno, outer.body[0].lineno, inner.lineno, inner.body[0].lineno


def parse_trace(trace_path, outer_body_line, inner_body_line):
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
        events.append((match.group("event"), int(match.group("line"))))

    if not events:
        fail("trace contains zero events for %s" % TARGET_FUNC)
    if not any(event == "call" for event, _ in events):
        fail("trace contains no call event for %s" % TARGET_FUNC)

    all_counts = []
    in_invocation = False
    current_inner_count = None
    completed_invocations = 0

    for event, line in events:
        if event == "call":
            if in_invocation:
                fail("overlapping target invocations are not supported")
            in_invocation = True
            current_inner_count = None
        elif event == "line" and in_invocation and line == outer_body_line:
            if current_inner_count is not None:
                all_counts.append(current_inner_count)
            current_inner_count = 0
        elif event == "line" and in_invocation and line == inner_body_line:
            if current_inner_count is None:
                fail("inner-loop body executed before an outer-loop body")
            current_inner_count += 1
        elif event == "return" and in_invocation:
            if current_inner_count is not None:
                all_counts.append(current_inner_count)
            current_inner_count = None
            in_invocation = False
            completed_invocations += 1

    if in_invocation:
        fail("trace ended during a target invocation")
    if completed_invocations == 0:
        fail("trace contains no completed target invocation")
    if not all_counts:
        fail("no executions of the nested loop were found")

    return {
        "max_iterations": max(all_counts),
        "min_iterations": min(all_counts),
    }


def build_question(outer_line, outer_body_line, inner_line, inner_body_line):
    return (
        "Run every pytest test method whose name begins with `test_` in class "
        f"`{TEST_CLASS}` from `{TEST_FILE}` (equivalently, the pytest selection "
        f"`{TEST_FILE}::{TEST_CLASS}`), and aggregate over ALL of those methods. "
        f"During that complete run, consider every invocation of `{TARGET_FUNC}` in "
        f"`{TARGET_FILE}`. An invocation means one call of that function and is numbered "
        "1-based in chronological call order across the complete pytest run; within an "
        "invocation, outer-loop iterations are likewise ordered chronologically. "
        f"The outer `for` loop has its header at absolute, 1-based source line {outer_line}, "
        f"and its body first executes at line {outer_body_line}. For each outer-loop "
        f"iteration, measure the nested `for` loop whose header is at absolute, 1-based "
        f"source line {inner_line}. Treat each restart of that nested loop for a new "
        "outer-loop iteration as a separate loop execution. One nested-loop iteration is "
        f"the Nth execution of its body's first line, line {inner_body_line}, in the target "
        "function's own frame; an execution that immediately takes `continue` still counts. "
        "A loop execution with no body-line execution has count 0. Count only line executions "
        f"from the `{TARGET_FUNC}` frame: exclude callees, comprehensions, and all other "
        "frames. Source lines are those in the named repository file as it exists for this "
        "run; for a multi-line statement, a line execution belongs to the absolute line on "
        "which that statement or expression begins. The function's `def` line, decorators, "
        "and docstring are not loop iterations. Keep every per-outer-iteration count (do not "
        "deduplicate), then take the maximum and minimum over all such counts from all "
        "invocations. Return exactly one JSON object with keys `max_iterations` and "
        "`min_iterations`, in that order; both values are JSON integers (not strings), with "
        "no additional keys or value formatting."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    outer_line, outer_body_line, inner_line, inner_body_line = locate_loops(root)
    answer = parse_trace(Path(args.trace_log), outer_body_line, inner_body_line)
    payload = {
        "question_kind": "M2_Loops",
        "question": build_question(
            outer_line, outer_body_line, inner_line, inner_body_line
        ),
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
