#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/webui/runner.py"
TARGET_FUNC_SUFFIXES = (".Runner._parse_train_args", "._parse_train_args")
TARGET_INVOCATION = 2
TARGET_VARIABLES = ["args", "ds_offload", "ds_stage", "finetuning_type", "model_name"]

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b.*$"
)
LOCALS_RE = re.compile(r"\blocals=(?P<locals>\{.*\})$")


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


def _parse_locals(raw_line: str) -> dict[str, str]:
    match = LOCALS_RE.search(raw_line)
    if match is None:
        raise SystemExit(f"Malformed trace line without locals payload: {raw_line}")
    payload = match.group("locals")
    try:
        parsed = ast.literal_eval(payload)
    except (ValueError, SyntaxError) as exc:
        raise SystemExit(f"Failed to parse locals payload: {payload}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"Locals payload is not a dict: {payload}")
    out = {}
    for key, value in parsed.items():
        out[str(key)] = value if isinstance(value, str) else repr(value)
    return out


def _extract_target_state(trace_lines: list[str]) -> dict[str, str]:
    matched_events = 0
    invocation_count = 0
    active_stack: list[int] = []
    captured_locals: dict[str, str] | None = None

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

        if event == "call":
            invocation_count += 1
            active_stack.append(invocation_count)
            continue

        if event == "line":
            if not active_stack:
                raise SystemExit("Malformed trace: line event observed without active Runner._parse_train_args call.")
            continue

        if event in {"return", "exception"}:
            if not active_stack:
                raise SystemExit("Malformed trace: return/exception observed without active Runner._parse_train_args call.")
            current_invocation = active_stack[-1]
            if event == "return" and current_invocation == TARGET_INVOCATION:
                captured_locals = _parse_locals(raw_line)
            active_stack.pop()
            continue

    if matched_events == 0:
        raise SystemExit("Trace contains zero events for target function Runner._parse_train_args.")
    if active_stack:
        raise SystemExit("Malformed trace: unterminated Runner._parse_train_args invocation.")
    if invocation_count < TARGET_INVOCATION:
        raise SystemExit(
            f"Expected at least {TARGET_INVOCATION} invocations of Runner._parse_train_args, found {invocation_count}."
        )
    if captured_locals is None:
        raise SystemExit(f"Could not capture return locals for invocation {TARGET_INVOCATION}.")

    missing = sorted(var for var in TARGET_VARIABLES if var not in captured_locals)
    if missing:
        raise SystemExit(f"Return locals are missing required variables: {missing}")

    return {name: captured_locals[name] for name in TARGET_VARIABLES}


def main() -> None:
    args = _parse_args()
    trace_lines = _read_trace_lines(Path(args.trace_log))
    observed = _extract_target_state(trace_lines)

    observed_state = [
        {"variable": name, "value": observed[name]}
        for name in sorted(observed.keys())
    ]

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": (
            "During execution of pytest test "
            "`llama_factory_qa/runner_parse_train_args_s3_state__r20260714/files/testcase.py::"
            "TestRunnerParseTrainArgsS3State::test_second_invocation_return_state`, "
            "consider function `src.llamafactory.webui.runner.Runner._parse_train_args` "
            "defined in `src/llamafactory/webui/runner.py`. "
            "Count invocations in 1-based order by each entry into this function during that single test run. "
            "For invocation 2, take the program point at function return (immediately after the return statement "
            "in that invocation is executed). "
            "Report the values of local variables `args`, `ds_offload`, `ds_stage`, `finetuning_type`, and "
            "`model_name` at that program point. Values must be reported as Python repr strings. "
            "Return JSON with exactly one key `observed_state`, whose value is an array of objects with keys "
            "`variable` (str) and `value` (str). Sort `observed_state` by `variable` in ascending lexicographic "
            "order; if duplicate variable names ever appear, break ties by `value` ascending lexicographic order."
        ),
        "template_answer": {
            "observed_state": [
                {"variable": "str", "value": "str"}
            ]
        },
        "oracle_answer": {
            "observed_state": observed_state
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], ensure_ascii=True))


if __name__ == "__main__":
    main()
