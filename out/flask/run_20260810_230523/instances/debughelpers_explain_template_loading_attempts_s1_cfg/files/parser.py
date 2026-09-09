#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/flask/debughelpers.py"
TARGET_FUNC = "flask.debughelpers.explain_template_loading_attempts"
TARGET_NAME = "explain_template_loading_attempts"
INVOCATION = 2

QUESTION = """Run the pytest test `flask_qa/debughelpers_explain_template_loading_attempts_s1_cfg/files/testcase.py::TestGeneratedTemplateLoadingAttempts::test_three_generated_diagnostic_runs`. During that test run, what is the exact ordered sequence of executed source-line events inside the 2nd invocation of `flask.debughelpers.explain_template_loading_attempts` in `src/flask/debughelpers.py`?

An invocation is one Python `call` event for this exact function, counted 1-based in chronological runtime-event order across the whole test. Select invocation 2 at its `call` event and stop at its corresponding `return` event. Include only Python `line` events emitted by that selected function's own frame; exclude its `call`, `return`, and `exception` events and all events from callers, callees (including `_dump_loader_info`), generator or comprehension frames, and every other invocation. Preserve chronological runtime-event order, using event-stream order as the tie-breaker if timestamps are equal. Retain every repeated line event; do not sort or deduplicate the sequence.

Line numbers are absolute, 1-based source line numbers in the named repository file as it exists for the test. Normalize a line event within a multi-line statement or expression to the line where its containing statement begins. This matters for the multi-line call in this function. The function's `def` line, parameter-continuation lines, decorator lines, and docstring line do not appear because they are not `line` events executed by the selected function body under these rules.

Return exactly one JSON object with the shape `{"executed_path": [{"file": "...", "func": "...", "line": 0}]}`. `executed_path` is a JSON array in the retained order described above. Every entry has exactly the keys `file`, `func`, and `line`, in that key order: `file` is the POSIX-style repository-relative JSON string `src/flask/debughelpers.py` with no leading repository prefix; `func` is the full dotted `module.qualname` JSON string `flask.debughelpers.explain_template_loading_attempts` (for format comparison, an unrelated method could be `flask.ctx.AppContext.push`); and `line` is a JSON integer, not a string. Do not apply `repr()` or `str()` wrapping to either string. The only output keys are `executed_path`, `file`, `func`, and `line`."""


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def statement_start_map(source_path: Path) -> dict[int, int]:
    if not source_path.is_file():
        fail(f"target source is missing: {source_path}")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_NAME
        ),
        None,
    )
    if target is None:
        fail(f"could not find target function {TARGET_NAME} in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and getattr(node, "end_lineno", None) is not None
    ]
    starts: dict[int, int] = {}
    for line in range(target.lineno, target.end_lineno + 1):
        containing = [
            node for node in statements if node.lineno <= line <= node.end_lineno
        ]
        if containing:
            chosen = min(
                containing,
                key=lambda node: (node.end_lineno - node.lineno, -node.lineno),
            )
            starts[line] = chosen.lineno
        else:
            starts[line] = line
    return starts


def parse_event(raw_line: str) -> dict[str, object] | None:
    match = re.match(
        r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} "
        r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
        r"event=(?P<event>\w+)\b",
        raw_line,
    )
    if match is None:
        return None
    return {
        "file": match.group("file").replace("\\", "/"),
        "line": int(match.group("line")),
        "func": match.group("func"),
        "event": match.group("event"),
    }


def harvest(
    trace_path: Path, source_path: Path
) -> dict[str, list[dict[str, object]]]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in raw.splitlines():
        event = parse_event(raw_line)
        if (
            event is not None
            and str(event["file"]).endswith(TARGET_FILE)
            and event["func"] == TARGET_FUNC
        ):
            events.append(event)
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    starts = statement_start_map(source_path)
    invocation_count = 0
    collecting = False
    completed = False
    executed_path: list[dict[str, object]] = []

    for event in events:
        if event["event"] == "call":
            invocation_count += 1
            if invocation_count == INVOCATION:
                collecting = True
            continue

        if not collecting:
            continue
        if event["event"] == "line":
            raw_line_number = int(event["line"])
            if raw_line_number not in starts:
                fail(f"line event {raw_line_number} is outside the target function")
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": starts[raw_line_number],
                }
            )
        elif event["event"] == "return":
            completed = True
            break

    if invocation_count < INVOCATION:
        fail(
            f"trace contains only {invocation_count} invocations of {TARGET_FUNC}, "
            f"expected at least {INVOCATION}"
        )
    if not completed:
        fail(f"invocation {INVOCATION} has no corresponding return event")
    if len(executed_path) < 50:
        fail(f"selected invocation has only {len(executed_path)} line events")
    if len({entry["line"] for entry in executed_path}) < 12:
        fail("selected invocation executes fewer than 12 distinct normalized lines")

    return {"executed_path": executed_path}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": harvest(args.trace_log, Path(TARGET_FILE)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
