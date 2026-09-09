#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/hparams/parser.py"
TARGET_FUNC_SUFFIX = ".get_train_args"
TARGET_INVOCATION = 2


TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def _read_trace_lines(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        raise SystemExit(f"Trace log not found: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise SystemExit(f"Trace log is empty: {trace_path}")
    return trace_path.read_text(encoding="utf-8").splitlines()


def _extract_invocation_lines(trace_lines: list[str]) -> tuple[int, dict[int, list[int]]]:
    invocation_count = 0
    active_stack: list[int] = []
    line_events_by_invocation: dict[int, list[int]] = {}
    matched_events = 0

    for raw in trace_lines:
        match = TRACE_RE.match(raw)
        if match is None:
            continue

        file_path = match.group("file").replace("\\", "/")
        func_name = match.group("func")
        if not file_path.endswith(TARGET_FILE_SUFFIX):
            continue
        if not func_name.endswith(TARGET_FUNC_SUFFIX):
            continue

        matched_events += 1
        event = match.group("event")
        lineno = int(match.group("lineno"))

        if event == "call":
            invocation_count += 1
            active_stack.append(invocation_count)
            line_events_by_invocation.setdefault(invocation_count, [])
            continue

        if event == "line":
            if not active_stack:
                raise SystemExit("Malformed trace: line event observed without active get_train_args call.")
            line_events_by_invocation[active_stack[-1]].append(lineno)
            continue

        if event in {"return", "exception"}:
            if not active_stack:
                raise SystemExit("Malformed trace: return/exception observed without active get_train_args call.")
            active_stack.pop()
            continue

    if matched_events == 0:
        raise SystemExit("Trace contains zero events for target function get_train_args.")
    if active_stack:
        raise SystemExit("Malformed trace: unterminated get_train_args invocation.")

    return invocation_count, line_events_by_invocation


def main() -> None:
    args = _parse_args()
    trace_path = Path(args.trace_log)
    out_path = Path(args.out)

    trace_lines = _read_trace_lines(trace_path)
    invocation_count, line_events_by_invocation = _extract_invocation_lines(trace_lines)

    if invocation_count < TARGET_INVOCATION:
        raise SystemExit(
            f"Expected at least {TARGET_INVOCATION} invocations of get_train_args, found {invocation_count}."
        )

    executed_line_sequence = line_events_by_invocation.get(TARGET_INVOCATION, [])
    if not executed_line_sequence:
        raise SystemExit(
            f"Invocation {TARGET_INVOCATION} exists but has no line events. "
            "Cannot produce non-empty control-flow answer."
        )

    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": (
            "During execution of pytest test "
            "`llama_factory_qa/parser_get_train_args_s1_cfg__r20260714/files/testcase.py::"
            "TestParserGetTrainArgsCFG::test_three_invocations_cfg_path`, "
            "consider function `src.llamafactory.hparams.parser.get_train_args` defined in "
            "`src/llamafactory/hparams/parser.py`. "
            "Count invocations in 1-based order by the sequence of function-entry events for this function "
            "within that single test run. For invocation 2, list the exact ordered sequence of executed source "
            "line numbers inside `get_train_args`, where an executed line means a line in this file that produces "
            "a Python line-execution event while this invocation is active. Preserve duplicates when a line executes "
            "multiple times and preserve temporal order exactly as executed. "
            "Return JSON with key `executed_line_sequence` whose value is a JSON array of integers."
        ),
        "template_answer": {"executed_line_sequence": ["int"]},
        "oracle_answer": {"executed_line_sequence": executed_line_sequence},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], ensure_ascii=True))


if __name__ == "__main__":
    main()
