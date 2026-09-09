#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/backends/vllm.py"
TARGET_FUNC = "instructlab.model.backends.vllm.build_vllm_cmd"
TARGET_NAME = "build_vllm_cmd"
INVOCATION = 2
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def statement_start_lines(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == TARGET_NAME
    ]
    if len(functions) != 1:
        fail(f"expected exactly one {TARGET_NAME} definition in {source_path}")
    function = functions[0]

    mapping: dict[int, int] = {}
    statement_types = (
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
        if isinstance(node, statement_types):
            for line in range(node.lineno, node.end_lineno + 1):
                mapping[line] = node.lineno
        elif isinstance(node, (ast.If, ast.While)):
            for line in range(node.test.lineno, node.test.end_lineno + 1):
                mapping[line] = node.lineno
    return mapping


def parse_trace(trace_path: Path, source_path: Path) -> list[dict]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    line_mapping = statement_start_lines(source_path)
    invocation_count = 0
    selected_active = False
    target_event_count = 0
    executed_path: list[dict] = []

    for raw_line in trace_text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if match.group("func") != TARGET_FUNC:
            continue
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_event_count += 1
        event = match.group("event")
        if event == "call":
            invocation_count += 1
            selected_active = invocation_count == INVOCATION
        elif event == "line" and selected_active:
            raw_line_number = int(match.group("line"))
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": line_mapping.get(raw_line_number, raw_line_number),
                }
            )
        elif event == "return" and selected_active:
            selected_active = False

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < 3:
        fail(
            f"expected invocation {INVOCATION} to be neither first nor last, "
            f"but found {invocation_count} invocation(s)"
        )
    if not executed_path:
        fail(f"invocation {INVOCATION} contains zero line events")
    return executed_path


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
        "`instruct_lab_qa/vllm_build_vllm_cmd_s1_cfg/files/testcase.py::"
        "TestVllmBuildPath::test_middle_server_uses_autodetected_configuration` "
        "against this repository. What is the exact ordered sequence of executed "
        "Python line events inside `instructlab.model.backends.vllm.build_vllm_cmd` "
        "in `src/instructlab/model/backends/vllm.py` during its second invocation? "
        "An invocation is one runtime `call` event for exactly that function, counted "
        "1-based in chronological order from the start of the test; calls of other "
        "functions, including nested comprehension frames, do not count. Include only "
        "`line` events emitted while that second function frame is active, beginning "
        "after its call event and ending before its return event. Exclude call, return, "
        "and exception events and all events in callees. The `def` line, decorator "
        "lines, and docstring lines do not appear in the sequence. Preserve "
        "chronological event order exactly and retain every duplicate; do not sort or "
        "deduplicate. Line numbers are absolute 1-based physical line numbers in the "
        "named repository file as it exists for this test. This function contains "
        "multi-line calls and expressions: if a line event occurs on any physical line "
        "spanned by one complete assignment, expression statement, raise, return, "
        "import, or augmented assignment, report the physical line where that statement "
        "begins; likewise, an event on any line spanned by an `if` or `while` condition "
        "is reported as the line where that condition begins. Retain one output entry "
        "per original event even when this normalization creates adjacent duplicates. "
        "For example, events on lines 20 and 21 of a hypothetical call expression whose "
        "statement begins on line 19 are both reported as line 19. Return exactly one "
        "JSON object with the key `executed_path`. Its value is a JSON array whose "
        "entries have exactly the keys `file`, `func`, and `line` in that key order. "
        "In every entry, `file` is the repo-relative POSIX path string, `func` is the "
        "fully qualified Python name in `module.qualname` form (for example, "
        "`package.module.Class.method`), and `line` is a JSON integer. Serialize the "
        "two strings as JSON strings and the integer as a JSON number; no field uses "
        "Python `repr`, and no value is null or omitted."
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
