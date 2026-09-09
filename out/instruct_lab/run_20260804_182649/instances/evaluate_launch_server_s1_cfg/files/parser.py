#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/evaluate.py"
TARGET_FUNC = "instructlab.model.evaluate.launch_server"
INVOCATION = 2
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def continuation_map(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "launch_server"
        ),
        None,
    )
    if function is None:
        fail(f"target function not found in {source_path}")

    mapping: dict[int, int] = {}
    simple_statement_types = (
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Expr,
        ast.Import,
        ast.ImportFrom,
        ast.Raise,
        ast.Return,
    )
    for node in ast.walk(function):
        if isinstance(node, simple_statement_types):
            for line in range(node.lineno, node.end_lineno + 1):
                mapping[line] = node.lineno
        elif isinstance(node, (ast.If, ast.While)):
            for line in range(node.test.lineno, node.test.end_lineno + 1):
                mapping[line] = node.lineno
    return mapping


def parse_trace(trace_path: Path, source_path: Path) -> list[dict]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    mapping = continuation_map(source_path)
    invocation = 0
    selected_active = False
    target_events = 0
    answer = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation += 1
            selected_active = invocation == INVOCATION
        elif event == "line" and selected_active:
            raw_number = int(match.group("line"))
            answer.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": mapping.get(raw_number, raw_number),
                }
            )
        elif event == "return" and selected_active:
            selected_active = False

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation < 3:
        fail(
            f"expected the selected invocation to be neither first nor last; "
            f"found only {invocation} invocation(s)"
        )
    if not answer:
        fail(f"invocation {INVOCATION} contains zero line events")
    return answer


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path(TARGET_FILE)
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    executed_path = parse_trace(Path(args.trace_log), source_path)
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/evaluate_launch_server_s1_cfg/files/testcase.py::"
        "TestEvaluateLaunchPath::test_branch_evaluation_reuses_serve_config` against "
        "this repository. What is the exact ordered sequence of executed Python "
        "line events inside `instructlab.model.evaluate.launch_server` in "
        "`src/instructlab/model/evaluate.py` during its second invocation? "
        "An invocation is one runtime `call` event for exactly that function, counted "
        "1-based in chronological order from the start of this test; calls of other "
        "functions do not count. Include only `line` events emitted while that second "
        "function frame is active, from its call up to but excluding its return event. "
        "Do not include call, return, or exception events, events in callees, decorator "
        "lines, or the `def` line; the function has no executable docstring, so no "
        "docstring line appears. Preserve chronological event order exactly and retain "
        "all duplicates; do not sort or deduplicate. Line numbers are 1-based physical "
        "line numbers in the named repository file as it exists for this test. For a "
        "multi-line statement or condition, normalize every line event on one of its "
        "continuation lines to the physical line where that complete statement or "
        "condition begins, retaining repeated normalized entries. For example, if a "
        "hypothetical assignment begins on line 20 and continues on lines 21 and 22, "
        "events while evaluating any of those three lines are each reported as line 20. "
        "Return exactly one JSON object with key `executed_path`. Its value is a JSON "
        "array whose entries have exactly the keys `file`, `func`, and `line` in that "
        "key order. In every entry, `file` is the repo-relative POSIX path string and "
        "`func` is the fully qualified Python name in `module.qualname` form (for "
        "example, `package.module.Class.method`); `line` is a JSON integer. Use JSON "
        "string serialization for the two strings and JSON number serialization for "
        "the integer; no value uses Python `repr`, and there are no null or omitted "
        "values."
    )
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": question,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {"executed_path": executed_path},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
