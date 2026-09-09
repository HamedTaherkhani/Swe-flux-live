#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/model/adapter.py"
TARGET_FUNC_SUFFIXES = ("._setup_freeze_tuning", "_setup_freeze_tuning")
TARGET_VARIABLES = [
    "cast_trainable_params_to_fp32",
    "module_name",
    "num_layers",
    "trainable_layer_ids",
    "trainable_layers",
]

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b.*$"
)
LOCALS_RE = re.compile(r"\blocals=(?P<locals>\{.*\})$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def read_trace_lines(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        raise RuntimeError(f"Trace log not found: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"Trace log is empty: {trace_path}")
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError(f"Trace log has no lines: {trace_path}")
    return lines


def parse_locals(raw_line: str) -> dict[str, str]:
    match = LOCALS_RE.search(raw_line)
    if match is None:
        raise RuntimeError(f"Malformed trace line without locals payload: {raw_line}")

    payload = match.group("locals")
    try:
        parsed = ast.literal_eval(payload)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(f"Failed to parse locals payload: {payload}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Locals payload is not a dict: {payload}")

    return {str(key): (value if isinstance(value, str) else repr(value)) for key, value in parsed.items()}


def collect_return_snapshots(trace_lines: list[str]) -> dict[int, dict[str, str]]:
    matched_events = 0
    stack_depth = 0
    invocation_index = 0
    snapshots: dict[int, dict[str, str]] = {}

    for raw_line in trace_lines:
        match = TRACE_RE.match(raw_line)
        if match is None:
            continue

        file_path = match.group("file").replace("\\", "/")
        func_name = match.group("func")
        if not file_path.endswith(TARGET_FILE_SUFFIX):
            continue
        if not any(func_name.endswith(suffix) for suffix in TARGET_FUNC_SUFFIXES):
            continue

        matched_events += 1
        event = match.group("event")
        locals_payload = parse_locals(raw_line)

        if event == "call":
            stack_depth += 1
            invocation_index += 1
            continue

        if stack_depth <= 0:
            raise RuntimeError("Malformed trace: target event found without an active _setup_freeze_tuning call.")

        if event == "return":
            missing = sorted(name for name in TARGET_VARIABLES if name not in locals_payload)
            if missing:
                raise RuntimeError(
                    f"Missing required locals at return of invocation {invocation_index}: {missing}"
                )
            snapshots[invocation_index] = {name: locals_payload[name] for name in TARGET_VARIABLES}
            stack_depth -= 1
        elif event == "exception":
            stack_depth -= 1

    if matched_events == 0:
        raise RuntimeError(
            "Trace contains zero events for target function llamafactory.model.adapter._setup_freeze_tuning."
        )
    if not snapshots:
        raise RuntimeError("No return snapshots were captured for _setup_freeze_tuning.")
    if stack_depth != 0:
        raise RuntimeError("Malformed trace: unterminated _setup_freeze_tuning invocation.")

    return snapshots


def build_oracle_answer(snapshots: dict[int, dict[str, str]]) -> dict:
    state_snapshots = []
    for invocation in sorted(snapshots.keys()):
        for variable in sorted(snapshots[invocation].keys()):
            state_snapshots.append(
                {
                    "invocation": invocation,
                    "variable": variable,
                    "value": snapshots[invocation][variable],
                }
            )
    state_snapshots.sort(key=lambda item: (item["invocation"], item["variable"], item["value"]))
    return {"state_snapshots": state_snapshots}


def build_question() -> str:
    return (
        "During execution of pytest test "
        "`llama_factory_qa/adapter_setup_freeze_tuning_m3_state/files/testcase.py::"
        "TestSetupFreezeTuningM3State::test_return_state_across_two_invocations`, analyze function "
        "`src.llamafactory.model.adapter._setup_freeze_tuning` defined in "
        "`src/llamafactory/model/adapter.py`. "
        "Define an invocation as one dynamic function entry for this target during that test run, counted in "
        "1-based order by occurrence. For each invocation that reaches a normal return, use the function's local "
        "variables at the return point, and treat each reported value as the Python `repr` string of that local at "
        "that moment. Compute values for exactly these local names: `cast_trainable_params_to_fp32`, `module_name`, "
        "`num_layers`, `trainable_layer_ids`, and `trainable_layers`. "
        "Return JSON with exactly one top-level key `state_snapshots` (array of objects). Each object must have "
        "`invocation` (int), `variable` (str), and `value` (str). Sort output deterministically by `invocation` "
        "ascending, then `variable` ascending lexicographic order, and if a tie remains, `value` ascending "
        "lexicographic order."
    )


def main() -> None:
    args = parse_args()
    trace_lines = read_trace_lines(Path(args.trace_log))
    snapshots = collect_return_snapshots(trace_lines)
    oracle_answer = build_oracle_answer(snapshots)

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": build_question(),
        "template_answer": {
            "state_snapshots": [
                {
                    "invocation": "int",
                    "variable": "str",
                    "value": "str",
                }
            ]
        },
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"[adapter_setup_freeze_tuning_m3_state] {exc}", file=sys.stderr)
        raise
