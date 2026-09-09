#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/scripts/convert_ckpt/llamafy_qwen.py"
TARGET_FUNC_SUFFIXES = (".save_weight", "save_weight")
SNAPSHOT_LINE = 58
SNAPSHOT_EXECUTIONS = (1, 3)
TARGET_VARIABLES = ["key", "llama_state_dict", "save_safetensors", "shard_size", "torch_dtype"]

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
        raise SystemExit(f"Trace log not found: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise SystemExit(f"Trace log is empty: {trace_path}")
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SystemExit(f"Trace log has no lines: {trace_path}")
    return lines


def parse_locals(raw_line: str) -> dict[str, str]:
    match = LOCALS_RE.search(raw_line)
    if match is None:
        raise SystemExit(f"Malformed trace line without locals payload: {raw_line}")
    payload = match.group("locals")
    try:
        parsed = ast.literal_eval(payload)
    except (SyntaxError, ValueError) as exc:
        raise SystemExit(f"Failed to parse locals payload: {payload}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"Locals payload is not a dict: {payload}")
    return {str(k): v if isinstance(v, str) else repr(v) for k, v in parsed.items()}


def collect_snapshots(trace_lines: list[str]) -> dict[str, dict[str, str]]:
    matched_events = 0
    active_stack: list[dict] = []
    snapshots: dict[str, dict[str, str]] = {}

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
        lineno = int(match.group("lineno"))
        locals_delta = parse_locals(raw_line)

        if event == "call":
            active_stack.append({"locals": {}, "line_counts": {}})

        if not active_stack:
            raise SystemExit("Malformed trace: target event found without an active save_weight invocation.")

        frame_state = active_stack[-1]
        frame_state["locals"].update(locals_delta)

        if event == "line":
            count = frame_state["line_counts"].get(lineno, 0) + 1
            frame_state["line_counts"][lineno] = count
            if lineno == SNAPSHOT_LINE and count in SNAPSHOT_EXECUTIONS:
                point_name = f"line_{SNAPSHOT_LINE}_exec_{count}"
                missing = sorted(name for name in TARGET_VARIABLES if name not in frame_state["locals"])
                if missing:
                    raise SystemExit(f"Missing variables at snapshot point {point_name}: {missing}")
                snapshots[point_name] = {name: frame_state["locals"][name] for name in TARGET_VARIABLES}

        if event in {"return", "exception"}:
            active_stack.pop()

    if matched_events == 0:
        raise SystemExit("Trace contains zero events for target function scripts.convert_ckpt.llamafy_qwen.save_weight.")
    if active_stack:
        raise SystemExit("Malformed trace: unterminated save_weight invocation.")

    for exec_count in SNAPSHOT_EXECUTIONS:
        point_name = f"line_{SNAPSHOT_LINE}_exec_{exec_count}"
        if point_name not in snapshots:
            raise SystemExit(f"Did not observe required snapshot point: {point_name}")

    return snapshots


def build_oracle_answer(snapshots: dict[str, dict[str, str]]) -> dict:
    ordered_points = sorted(
        snapshots.keys(),
        key=lambda name: int(name.rsplit("_", 1)[1]),
    )
    state_snapshots = []
    for point_name in ordered_points:
        for variable in sorted(snapshots[point_name].keys()):
            state_snapshots.append(
                {
                    "point": point_name,
                    "variable": variable,
                    "value": snapshots[point_name][variable],
                }
            )
    return {"state_snapshots": state_snapshots}


def main() -> None:
    args = parse_args()
    trace_lines = read_trace_lines(Path(args.trace_log))
    snapshots = collect_snapshots(trace_lines)
    oracle_answer = build_oracle_answer(snapshots)

    question = (
        "During execution of pytest test "
        "`llama_factory_qa/llamafy_qwen_save_weight_m3_state/files/testcase.py::"
        "TestLlamafyQwenSaveWeightM3State::test_conversion_loop_state_snapshots`, "
        "analyze function `scripts.convert_ckpt.llamafy_qwen.save_weight` defined in "
        "`scripts/convert_ckpt/llamafy_qwen.py`. "
        "Count executions of source line 58 in 1-based order within a single invocation of this function during "
        "that test run. Define program points `line_58_exec_1` and `line_58_exec_3` as the first and third "
        "executions of line 58, respectively. At each program point, report the local-variable values for "
        "`key`, `llama_state_dict`, `save_safetensors`, `shard_size`, and `torch_dtype`, where each value is "
        "the Python repr string for that local at that exact program point. "
        "Return JSON with exactly one top-level key `state_snapshots` whose value is an array of objects with keys "
        "`point` (str), `variable` (str), and `value` (str). Sort by `point` using execution index order "
        "(exec_1 before exec_3), then by `variable` in ascending lexicographic order; if ties remain, sort by "
        "`value` ascending lexicographic order."
    )

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": question,
        "template_answer": {
            "state_snapshots": [
                {
                    "point": "str",
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
    main()

