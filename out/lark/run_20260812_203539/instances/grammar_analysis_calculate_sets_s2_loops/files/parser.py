#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "lark/parsers/grammar_analysis.py"
TARGET_FUNC = "lark.parsers.grammar_analysis.calculate_sets"
TEST_ID = (
    "lark_qa/grammar_analysis_calculate_sets_s2_loops/files/testcase.py"
    "::TestCalculateSetsLoopDynamics::test_seeded_dependency_propagation"
)


def fail(message):
    raise RuntimeError(message)


def locate_loop(root):
    source_path = root / TARGET_FILE
    if not source_path.is_file():
        fail("target source is missing: %s" % source_path)

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "calculate_sets"
        ),
        None,
    )
    if function is None:
        fail("could not locate calculate_sets in %s" % source_path)

    loop = next((node for node in function.body if isinstance(node, ast.While)), None)
    if loop is None or not loop.body:
        fail("could not locate the first top-level while loop in calculate_sets")
    return loop.lineno, loop.body[0].lineno


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
                fail("overlapping calculate_sets invocations are not supported")
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
        f"Run exactly the pytest test `{TEST_ID}`. During that test, consider the first "
        f"invocation of `{TARGET_FUNC}` in `{TARGET_FILE}`. An invocation means one call "
        "of that function and invocations are numbered 1-based in chronological call order "
        "during the stated pytest run. In that first invocation, how many iterations does "
        f"the `while` loop whose header is at absolute, 1-based source line {loop_line} "
        f"perform? Define iteration N (counted 1-based) as the Nth execution of the loop "
        f"body's first statement, at line {body_line}, in the target function's own frame. "
        "Count only executions in that frame; exclude events in `update_set`, comprehensions, "
        "and every other callee or frame. Source line numbers refer to the named repository "
        "file as it exists for this run. For a multi-line statement or expression, execution "
        "is attributed to the absolute line where that statement or expression begins. The "
        "function's `def` line, decorator lines, and docstring lines do not count as loop "
        "iterations. Do not deduplicate any iterations and apply no sorting: return the total "
        "chronological count. Return exactly one JSON object with the sole key "
        "`loop_iteration_count`; its value must be a JSON integer, not a string, with no "
        "additional keys or formatting."
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
