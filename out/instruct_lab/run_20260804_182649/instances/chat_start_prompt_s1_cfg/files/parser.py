#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/model/chat.py"
TARGET_FUNC = "instructlab.model.chat.ConsoleChatBot.start_prompt"
INVOCATION = 9
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test `instruct_lab_qa/chat_start_prompt_s1_cfg/files/testcase.py::TestChatStartPromptCFG::test_middle_streaming_invocation` and consider `ConsoleChatBot.start_prompt` in `src/instructlab/model/chat.py`. What is the exact ordered control-flow path inside the ninth invocation of that function?

An invocation is one Python `call` event for `instructlab.model.chat.ConsoleChatBot.start_prompt`, counted 1-based in chronological order over the complete test run; thus the requested invocation is the ninth such call. Only Python `line` events produced by that invocation's own frame count. Exclude its `call`, `return`, and `exception` events, and exclude every event in callees or any other frame.

For each counted event, report the source line on which the innermost Python AST statement (or exception-handler clause) containing that event begins. This normalization applies to all multi-line calls, conditions, literals, and other multi-line statements: for example, an event on continuation line 901 of a statement beginning on line 899 is reported as 899. Line numbers are absolute 1-based physical line numbers in the named target file as it exists in the repository. The `def` line and any decorator lines do not appear because definition/call events are excluded; this function also has no executable docstring line at entry.

Return exactly one JSON object with the shape `{"executed_path": [{"file": "str", "func": "str", "line": "int"}]}`. Each list element corresponds to one counted line event. Set `file` to the repo-relative POSIX path `src/instructlab/model/chat.py`, set `func` to the fully qualified Python name `instructlab.model.chat.ConsoleChatBot.start_prompt` (the naming format is `module.Class.method`, for example `pkg.mod.Widget.run`), and encode `line` as a JSON integer. Preserve total chronological event order, using original event order as the tie-breaker when normalized line numbers are equal. Do not sort or deduplicate: repeated executions of the same source statement must produce repeated objects. No reported value uses `repr`, `str`, null, or an exception-name convention; the two strings are the fixed values specified above and line numbers are JSON integers."""


def statement_start_map(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.stmt, ast.ExceptHandler))
        and hasattr(node, "lineno")
        and hasattr(node, "end_lineno")
    ]
    mapping: dict[int, int] = {}
    for line in range(1, len(source_path.read_text(encoding="utf-8").splitlines()) + 1):
        containing = [
            node for node in nodes if node.lineno <= line <= node.end_lineno
        ]
        if containing:
            innermost = min(
                containing,
                key=lambda node: (
                    node.end_lineno - node.lineno,
                    -node.lineno,
                    node.col_offset,
                ),
            )
            mapping[line] = innermost.lineno
    return mapping


def parse_path(trace_path: Path, source_path: Path) -> list[dict[str, object]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    starts = statement_start_map(source_path)
    invocation_number = 0
    selected_active = False
    target_events = 0
    executed_path: list[dict[str, object]] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation_number += 1
            selected_active = invocation_number == INVOCATION
            continue
        if event == "return":
            if selected_active:
                selected_active = False
            continue
        if event != "line" or not selected_active:
            continue

        physical_line = int(match.group("line"))
        if physical_line not in starts:
            raise RuntimeError(
                f"no containing AST statement for executed line {physical_line}"
            )
        executed_path.append(
            {
                "file": TARGET_FILE,
                "func": TARGET_FUNC,
                "line": starts[physical_line],
            }
        )

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_number < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_number} target invocations; "
            f"cannot select invocation {INVOCATION}"
        )
    if not executed_path:
        raise RuntimeError(f"invocation {INVOCATION} contains zero line events")
    return executed_path


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True, type=Path)
    arg_parser.add_argument("--out", required=True, type=Path)
    args = arg_parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    source_path = repo_root / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": {
            "executed_path": parse_path(args.trace_log, source_path)
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
