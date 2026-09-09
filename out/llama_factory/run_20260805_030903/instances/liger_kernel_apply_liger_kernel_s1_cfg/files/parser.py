from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/llamafactory/model/model_utils/liger_kernel.py"
TARGET_FUNC = "llamafactory.model.model_utils.liger_kernel.apply_liger_kernel"
INVOCATION = 4
EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the single pytest test `llama_factory_qa/liger_kernel_apply_liger_kernel_s1_cfg/files/testcase.py::TestLigerKernelControlFlow::test_generated_model_loading_scenarios` and report the concrete control-flow path through `llamafactory.model.model_utils.liger_kernel.apply_liger_kernel` in `src/llamafactory/model/model_utils/liger_kernel.py` for its fourth invocation.

An invocation is one `call` event for exactly that function, counted 1-based in chronological order during this single test run; calls of `load_model`, imported Liger backends, helpers, or any other functions do not count. For invocation 4, include only executable line events emitted by that invocation's own frame after its call event and before its matching return event. Exclude call, return, and exception events and every event in callees. Preserve every included event in chronological order, including repeated visits to the same source statement; do not sort or deduplicate the path.

Line numbers are absolute 1-based physical source line numbers in the named repository file as it exists for the test run. Normalize an event on a physical continuation line of a multi-line statement or expression to the line where its innermost enclosing AST statement begins; for example, an event on a later argument line of a multi-line assignment is reported at that assignment's first line. This function contains a multi-line signature and may execute a multi-line condition, so this normalization applies. The `def` line does not appear because the call event is excluded; decorator and docstring lines also do not appear. The sequence consists only of the normalized executable line events defined above.

Return exactly one JSON object with shape `{"executed_path": [{"file": "str", "func": "str", "line": "int"}]}`. In every element, `file` is the repo-relative POSIX path string `src/llamafactory/model/model_utils/liger_kernel.py`, `func` is the fully qualified Python name string `llamafactory.model.model_utils.liger_kernel.apply_liger_kernel` in `module.qualname` format (for example, `package.module.Class.method`), and `line` is the normalized JSON integer line number. The list order is exactly the chronological event order specified above, with duplicates retained."""


def statement_start_lines(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "apply_liger_kernel"
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and node.end_lineno is not None
    ]
    mapping: dict[int, int] = {}
    for line in range(target.lineno + 1, target.end_lineno + 1):
        enclosing = [node for node in statements if node.lineno <= line <= node.end_lineno]
        if enclosing:
            innermost = min(enclosing, key=lambda node: (node.end_lineno - node.lineno, -node.lineno))
            mapping[line] = innermost.lineno
        else:
            mapping[line] = line
    return mapping


def parse_trace(trace_path: Path, source_path: Path) -> dict[str, list[dict[str, object]]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        events.append((match.group("event"), int(match.group("line"))))

    if not events:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")

    starts = statement_start_lines(source_path)
    invocation_count = 0
    collecting = False
    saw_return = False
    path: list[dict[str, object]] = []
    for event, line in events:
        if event == "call":
            invocation_count += 1
            collecting = invocation_count == INVOCATION
            continue
        if not collecting:
            continue
        if event == "line":
            path.append({"file": TARGET_FILE, "func": TARGET_FUNC, "line": starts.get(line, line)})
        elif event == "return":
            saw_return = True
            collecting = False
            break

    if invocation_count < INVOCATION:
        raise RuntimeError(
            f"trace has only {invocation_count} invocation(s) of {TARGET_FUNC}; "
            f"invocation {INVOCATION} is required"
        )
    if not saw_return:
        raise RuntimeError(f"invocation {INVOCATION} has no matching return event for {TARGET_FUNC}")
    if not path:
        raise RuntimeError(f"invocation {INVOCATION} has zero line events for {TARGET_FUNC}")
    return {"executed_path": path}


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    root_dir = Path(__file__).resolve().parents[3]
    source_path = root_dir / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    oracle_answer = parse_trace(args.trace_log, source_path)
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"executed_path": [{"file": "str", "func": "str", "line": "int"}]},
        "oracle_answer": oracle_answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote oracle with {len(oracle_answer['executed_path'])} path events to {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
