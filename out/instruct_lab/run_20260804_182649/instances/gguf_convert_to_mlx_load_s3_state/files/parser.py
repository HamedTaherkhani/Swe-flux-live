#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/mlx_explore/gguf_convert_to_mlx.py"
TARGET_FUNC = "instructlab.mlx_explore.gguf_convert_to_mlx.load"
OBSERVATION_LINE = 282
CAPTURE_LINE = 283
OBSERVATION_OCCURRENCE = 3
EXPECTED_INVOCATIONS = 4
VARIABLES = ("config", "gguf_ft", "quantization", "weights")
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
    if not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        fail(f"locals on trace line {trace_line} do not map strings to repr strings")
    return value


def extract_observed_state(trace_path: Path) -> list[dict[str, str]]:
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
    previous_line: int | None = None

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
            previous_line = None
        frame_state.update(changed)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            occurrence_count += 1
        if (
            event == "line"
            and int(match.group("line")) == CAPTURE_LINE
            and previous_line == OBSERVATION_LINE
            and occurrence_count == OBSERVATION_OCCURRENCE
        ):
            missing = [name for name in VARIABLES if name not in frame_state]
            if missing:
                fail(
                    "observation is missing requested local(s): " + ", ".join(missing)
                )
            selected = {name: frame_state[name] for name in VARIABLES}

        if event == "line":
            previous_line = int(match.group("line"))

        if event in {"return", "exception"}:
            frame_state = {}
            previous_line = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count != EXPECTED_INVOCATIONS:
        fail(
            f"expected exactly {EXPECTED_INVOCATIONS} target invocations; "
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

    observed_state = extract_observed_state(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/gguf_convert_to_mlx_load_s3_state/files/"
        "testcase.py::TestIndirectGgufConversion::test_training_prepares_generated_models` "
        "against this repository. In "
        "`instructlab.mlx_explore.gguf_convert_to_mlx.load` in "
        "`src/instructlab/mlx_explore/gguf_convert_to_mlx.py`, what are the "
        "concrete values of the local variables `config`, `gguf_ft`, "
        "`quantization`, and `weights` immediately after physical line 282 has "
        "executed for the third time during the complete test run? Physical line "
        "numbers are absolute and 1-based in the named file as it exists for this "
        "test. Line 282 is a single-line assignment, and 'immediately after' means "
        "the state in that same function frame when control reaches the next "
        "executable line, physical line 283; neither the `def` line, comments, nor "
        "docstring-only lines count as executions. Count only executions by a frame "
        "of exactly the named function, excluding callees, comprehension frames, "
        "and other functions. Count chronologically and 1-based across the whole "
        "test run, retain duplicate executions, and do not deduplicate. An "
        "invocation means one runtime call of exactly the named function, counted "
        "chronologically and 1-based; the test makes four such invocations, but the "
        "requested point is selected solely by the third execution of line 282, "
        "including only invocations that reach that line. Report every local value "
        "as the exact Python `repr()` string of the whole value at that moment, "
        "without truncation or normalization. For a container, use the Python "
        "`repr()` of the whole container rather than recursively converting it to "
        "JSON, so contained strings keep Python quotes and `None` and `True` use "
        "Python spellings (for example, a hypothetical list would be represented "
        "by the JSON string \"[6, 'demo']\"). Embedded newline characters in a repr "
        "are real characters in the value and are escaped only by the enclosing "
        "JSON serialization. All requested locals exist; do not substitute an "
        "empty string, omit an entry, or use JSON `null`. Return exactly one JSON "
        "object with the key `observed_state`. Its value is a JSON array containing "
        "one entry for each requested variable, sorted by bare variable name in "
        "ascending Unicode code-point order; there are no ties, and entries and "
        "values are not deduplicated. Each entry has exactly the keys `value` and "
        "`variable` in that key order, both mapped to JSON strings. The `variable` "
        "string is the bare local name, and the `value` string is its Python repr "
        "as defined above."
    )
    payload = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": {"observed_state": observed_state},
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
