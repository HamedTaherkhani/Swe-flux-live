#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/parse_tree_builder.py"
TARGET_FUNC = "lark.parse_tree_builder.ParseTreeBuilder.create_callback"
TEST_ID = (
    "lark_qa/parse_tree_builder_create_callback_s2_loops/files/testcase.py"
    "::TestCreateCallbackLoopDynamics::test_seeded_rule_builder_matrix"
)


def fail(message):
    raise RuntimeError(message)


def locate_loop(root):
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail("target source is missing: %s" % source_path)

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ParseTreeBuilder"
        ),
        None,
    )
    if target_class is None:
        fail("could not locate ParseTreeBuilder in %s" % source_path)

    function = next(
        (
            node
            for node in target_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "create_callback"
        ),
        None,
    )
    if function is None:
        fail("could not locate ParseTreeBuilder.create_callback in %s" % source_path)

    selected = next(
        (
            node
            for node in ast.walk(function)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "w"
            and isinstance(node.iter, ast.Name)
            and node.iter.id == "wrapper_chain"
        ),
        None,
    )
    if selected is None or not selected.body:
        fail("could not locate the wrapper_chain loop in ParseTreeBuilder.create_callback")
    return selected.lineno, selected.body[0].lineno


def parse_trace(trace_path, body_line):
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

    in_first_invocation = False
    first_completed = False
    iteration_count = 0
    for event, line in events:
        if event == "call":
            if not in_first_invocation and not first_completed:
                in_first_invocation = True
            elif in_first_invocation:
                fail("overlapping create_callback invocations are not supported")
        elif event == "line" and in_first_invocation and line == body_line:
            iteration_count += 1
        elif event == "return" and in_first_invocation:
            in_first_invocation = False
            first_completed = True
            break

    if in_first_invocation:
        fail("trace ended during the first target invocation")
    if not first_completed:
        fail("trace contains no completed target invocation")
    if iteration_count == 0:
        fail("the selected loop body did not execute")
    return {"loop_iteration_count": iteration_count}


def build_question(loop_line, body_line):
    return (
        f"Run exactly the pytest test `{TEST_ID}` (class "
        "`TestCreateCallbackLoopDynamics`, method `test_seeded_rule_builder_matrix`). "
        f"During that test, consider invocation 1 of `{TARGET_FUNC}` in `{TARGET_FILE}`. "
        "An invocation means one call of that function during the stated test run, and "
        "invocations are numbered 1-based in chronological call order. How many iterations "
        f"does the `for` loop whose header is at absolute, 1-based source line {loop_line} "
        "perform over the entirety of that invocation? The same loop statement is reached "
        "from an enclosing loop, so aggregate all of its entries during invocation 1. Define "
        "iteration N, counted 1-based, as the Nth chronological execution of the loop body's "
        f"first statement, which begins at line {body_line}, in the target function's own "
        "frame. Count every such execution, including repeated executions with equal local "
        "values; do not deduplicate or sort. Exclude executions in wrappers, callbacks, "
        "comprehensions, and all other callees or frames. Source line numbers refer to the "
        "named repository file as it exists for this run. For a multi-line statement or "
        "expression, execution is attributed to the absolute line where that statement or "
        "expression begins. The function's `def` line, decorator lines, and docstring lines "
        "do not count as iterations. Return exactly one JSON object with the sole key "
        "`loop_iteration_count`; its value must be the total as a JSON integer (not a string), "
        "with no additional keys."
    )


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    loop_line, body_line = locate_loop(root)
    answer = parse_trace(Path(args.trace_log), body_line)
    payload = {
        "question_kind": "S2_Loops",
        "question": build_question(loop_line, body_line),
        "template_answer": {"loop_iteration_count": "int"},
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
