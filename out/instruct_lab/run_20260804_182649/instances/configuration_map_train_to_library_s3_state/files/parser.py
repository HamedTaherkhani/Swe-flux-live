#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/configuration.py"
TARGET_FUNC = "instructlab.configuration.map_train_to_library"
OBSERVATION_LINE = 1564
OBSERVATION_OCCURRENCE = 3
VARIABLES = (
    "ds_args",
    "fsdp_args",
    "lora_args",
    "lora_enabled",
    "lora_options",
    "torch_args",
    "train_args",
)
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b.*? locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_changed_locals(text: str, trace_line: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals on trace line {trace_line}: {exc}")
    if not isinstance(value, dict):
        fail(f"locals on trace line {trace_line} are not a dictionary")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        fail(f"locals on trace line {trace_line} do not map strings to repr strings")
    return value


def observed_state(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_count = 0
    occurrence_count = 0
    frame_state: dict[str, str] = {}
    selected: dict[str, str] | None = None

    for trace_line, raw_line in enumerate(text.splitlines(), start=1):
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        changed = parse_changed_locals(match.group("locals"), trace_line)

        if event == "call":
            invocation_count += 1
            frame_state = {}
        frame_state.update(changed)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            occurrence_count += 1
            if occurrence_count == OBSERVATION_OCCURRENCE:
                missing = [name for name in VARIABLES if name not in frame_state]
                if missing:
                    fail(
                        "observation is missing requested local(s): "
                        + ", ".join(missing)
                    )
                selected = {name: frame_state[name] for name in VARIABLES}

        if event in {"return", "exception"}:
            frame_state = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < OBSERVATION_OCCURRENCE:
        fail(
            f"expected at least {OBSERVATION_OCCURRENCE} target invocations; "
            f"found {invocation_count}"
        )
    if occurrence_count != OBSERVATION_OCCURRENCE:
        fail(
            f"expected exactly {OBSERVATION_OCCURRENCE} executions of line "
            f"{OBSERVATION_LINE}; found {occurrence_count}"
        )
    if selected is None:
        fail("the requested observation point was not captured")

    return [
        {"value": selected[variable], "variable": variable}
        for variable in sorted(VARIABLES)
    ]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = observed_state(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/configuration_map_train_to_library_s3_state/files/"
        "testcase.py::TestTrainConfigurationMapping::test_generated_lora_cli_runs` "
        "against this repository. In `instructlab.configuration.map_train_to_library` "
        "in `src/instructlab/configuration.py`, what are the concrete values of the "
        "local variables `ds_args`, `fsdp_args`, `lora_args`, `lora_enabled`, "
        "`lora_options`, `torch_args`, and `train_args` immediately after physical "
        "line 1563 has executed for the third time during the test run? Line numbers "
        "are absolute, 1-based physical line numbers in the named file as it exists "
        "for this test. Line 1563 is a single-line assignment; its execution is "
        "complete when control reaches the following executable line in that same "
        "function frame. Count an execution only when that line is executed by an "
        "active frame of exactly the named function; executions in callees or other "
        "functions do not count. Count chronologically and 1-based across the whole "
        "test run, retaining every execution; do not deduplicate. An invocation means "
        "one runtime call of exactly the named function, also counted chronologically "
        "and 1-based, although the requested point is selected by line execution count "
        "rather than by invocation number. Report each value as the exact Python "
        "`repr()` string of the whole local value at that moment, with no truncation "
        "or normalization. For a container or model object, use the `repr()` of the "
        "whole object rather than recursively converting it to JSON; thus strings "
        "inside such a repr retain Python quotes and `None` and `True` retain Python "
        "spellings (a hypothetical list could be represented by the JSON string "
        "\"[4, 'sample']\"). Any embedded newline characters in a repr string are "
        "included as real characters and escaped only as required by JSON encoding. "
        "No requested variable is absent, and no missing value, empty string, or JSON "
        "`null` sentinel is used. Return exactly one JSON object with key "
        "`observed_state`. Its value is a JSON array with one entry per requested "
        "variable, sorted by the variable name in ascending Unicode code-point order; "
        "there are no ties and no deduplication. Each entry has exactly the keys "
        "`value` and `variable` in that key order, and both values are JSON strings. "
        "`variable` is the bare local-variable name and `value` is its Python repr "
        "string as defined above."
    )
    payload = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": answer},
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
