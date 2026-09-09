from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/framework/cli/starters.py"
TARGET_FUNC = (
    "kedro.framework.cli.starters._validate_config_file_against_prompts"
)
INVOCATION = 9

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def statement_start_map(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    mapping: dict[int, int] = {}
    candidates: dict[int, list[ast.stmt]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt) or isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        end_lineno = getattr(node, "end_lineno", node.lineno)
        for lineno in range(node.lineno, end_lineno + 1):
            candidates.setdefault(lineno, []).append(node)

    for lineno, statements in candidates.items():
        innermost = min(
            statements,
            key=lambda node: (
                getattr(node, "end_lineno", node.lineno) - node.lineno,
                -node.lineno,
                type(node).__name__,
            ),
        )
        mapping[lineno] = innermost.lineno
    return mapping


def parse_events(trace_path: Path) -> list[tuple[str, int, str, str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int, str, str]] = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        file_name = match.group("file").replace("\\", "/")
        func = match.group("func")
        if file_name.endswith("/" + TARGET_FILE) and func == TARGET_FUNC:
            events.append(
                (
                    match.group("event"),
                    int(match.group("line")),
                    file_name,
                    func,
                )
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def build_answer(
    events: list[tuple[str, int, str, str]], source_path: Path
) -> dict[str, list[dict[str, object]]]:
    starts = [
        position
        for position, (event, _line, _file, _func) in enumerate(events)
        if event == "call"
    ]
    if len(starts) < INVOCATION:
        fail(
            f"expected at least {INVOCATION} calls to {TARGET_FUNC}, "
            f"found {len(starts)}"
        )

    begin = starts[INVOCATION - 1]
    end = starts[INVOCATION] if len(starts) > INVOCATION else len(events)
    normalization = statement_start_map(source_path)
    line_numbers = [
        normalization.get(line, line)
        for event, line, _file, _func in events[begin:end]
        if event == "line"
    ]
    if not line_numbers:
        fail(f"invocation {INVOCATION} contains zero line events")

    return {
        "executed_path": [
            {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
            for line in line_numbers
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        fail(f"target source does not exist: {source_path}")

    answer = build_answer(parse_events(args.trace_log), source_path)
    question = (
        "Run the pytest test "
        "`kedro_qa/starters_validate_config_file_against_prompts_s1_cfg/"
        "files/testcase.py::TestGeneratedConfigPaths::test_varied_config_files` "
        "and consider calls to "
        "`kedro.framework.cli.starters._validate_config_file_against_prompts` "
        "in `kedro/framework/cli/starters.py`. What is the exact ordered "
        "sequence of executed source-line events within its ninth invocation? "
        "An invocation is one Python `call` event for this function, counted "
        "1-based in chronological order during this test; include only `line` "
        "events emitted by that ninth function frame, from its call until it "
        "returns or raises, and exclude call, return, and exception events. "
        "Preserve chronological order and preserve repeated line events; do "
        "not sort or deduplicate the sequence. Report line numbers as absolute "
        "1-based source line numbers in the named repository file as it exists "
        "for the run. The `def` line, decorator lines, and docstring lines do "
        "not appear. For a line event attributed to any physical continuation "
        "line of a multi-line statement, report the line where the innermost "
        "containing statement begins; this function contains multi-line calls "
        "and raises, and separate events that normalize to the same starting "
        "line remain separate. Return exactly an object with key "
        "`executed_path`, whose value is a JSON array of objects with exactly "
        "these keys: `file` (JSON string), `func` (JSON string), and `line` "
        "(JSON integer). In every element, `file` is the repo-relative POSIX "
        "path `kedro/framework/cli/starters.py`, and `func` is the fully "
        "qualified dotted name "
        "`kedro.framework.cli.starters._validate_config_file_against_prompts` "
        "(for example, this naming format would render a method as "
        "`package.module.Class.method`)."
    )
    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": question,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
