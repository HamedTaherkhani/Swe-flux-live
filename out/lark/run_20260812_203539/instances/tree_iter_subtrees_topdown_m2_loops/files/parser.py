#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/tree.py"
TARGET_FUNC = "lark.tree.Tree.iter_subtrees_topdown"
TEST_FILE = "lark_qa/tree_iter_subtrees_topdown_m2_loops/files/testcase.py"
TEST_CLASS = "TestTopdownTraversalLoopDynamics"


def fail(message):
    raise RuntimeError(message)


def locate_target_lines(root):
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
            and node.name == "iter_subtrees_topdown"
        ),
        None,
    )
    if function is None:
        fail("could not locate Tree.iter_subtrees_topdown in %s" % source_path)

    executable_body = list(function.body)
    if (
        executable_body
        and isinstance(executable_body[0], ast.Expr)
        and isinstance(executable_body[0].value, (ast.Str, ast.Constant))
        and isinstance(getattr(executable_body[0].value, "value", None), str)
    ):
        executable_body = executable_body[1:]
    if not executable_body:
        fail("target function has no executable body")

    loop = next((node for node in ast.walk(function) if isinstance(node, ast.While)), None)
    if loop is None or not loop.body:
        fail("could not locate the while-loop in Tree.iter_subtrees_topdown")
    return executable_body[0].lineno, loop.lineno, loop.body[0].lineno


def parse_trace(trace_path, setup_line, loop_body_line):
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

    iteration_counts = []
    for event, line in events:
        if event != "line":
            continue
        if line == setup_line:
            iteration_counts.append(0)
        elif line == loop_body_line:
            if not iteration_counts:
                fail("loop body executed before any logical invocation began")
            iteration_counts[-1] += 1

    if not iteration_counts:
        fail("trace contains no logical target invocations")
    if not 10 <= len(iteration_counts) <= 15:
        fail(
            "expected 10 to 15 logical target invocations, observed %s"
            % len(iteration_counts)
        )
    if not all(count > 0 for count in iteration_counts):
        fail("at least one selected while-loop body never executed")
    if len(set(iteration_counts)) < 6:
        fail("fewer than six distinct per-invocation loop counts were observed")

    return {
        "max_iterations": max(iteration_counts),
        "min_iterations": min(iteration_counts),
    }


def build_question(loop_line, loop_body_line):
    return (
        f"Run every pytest test method whose name begins with `test_` in class "
        f"`{TEST_CLASS}` from `{TEST_FILE}` (equivalently, select "
        f"`{TEST_FILE}::{TEST_CLASS}`), and aggregate over ALL collected methods in "
        "that class. Identify a method by its full pytest id "
        f"`{TEST_FILE}::{TEST_CLASS}::method_name`. Use pytest's collected execution "
        "order for methods and chronological execution order within each method. During "
        f"that complete run, consider every invocation of `{TARGET_FUNC}` in "
        f"`{TARGET_FILE}`. Invocation means one evaluation of a call to this generator "
        "function, producing one generator object; number invocations 1-based in "
        "chronological call order. Resuming the same suspended generator, including after "
        "a `yield`, remains part of its original invocation and never creates another "
        "invocation. Each selected test method makes one such direct call and exhausts its "
        f"generator. For each invocation, count iterations of the `while` loop whose header "
        f"is at absolute, 1-based source line {loop_line}. Define iteration N (also 1-based) "
        f"as the Nth execution of the loop body's first statement, `node = stack_pop()`, "
        f"at absolute line {loop_body_line}, in that invocation's own generator frame over "
        "the generator's entire lifetime. Thus, an item popped from `stack` counts once "
        "whether it is a `Tree` or a non-Tree value; an execution that subsequently reaches "
        "`continue` still counts. Do not count evaluations of the `while` condition, "
        "iterations of the nested `for` loop, generator resumptions, or executions in any "
        "callee or other frame. An invocation whose loop body never executes has count 0. "
        "Source lines are absolute, 1-based lines in the named repository file as it exists "
        "for this run. For a multi-line statement or expression, attribute execution to the "
        "line where that statement or expression begins. The `def` line, decorator lines, "
        "and docstring lines are not iterations. Retain one count for every invocation, "
        "including duplicate counts; do not deduplicate or sort them before taking extrema. "
        "Compute the maximum and minimum over all retained per-invocation counts across all "
        "test methods. Return exactly one JSON object with keys `max_iterations` and "
        "`min_iterations`, in that order. Both values are JSON integers, not strings; use no "
        "value formatting such as `str()` or `repr()`, and emit no additional keys."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    setup_line, loop_line, loop_body_line = locate_target_lines(root)
    answer = parse_trace(Path(args.trace_log), setup_line, loop_body_line)
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
