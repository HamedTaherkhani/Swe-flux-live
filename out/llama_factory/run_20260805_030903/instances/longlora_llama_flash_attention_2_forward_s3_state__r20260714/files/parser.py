import argparse
import ast
import json
import re
from pathlib import Path


INSTANCE_ID = "longlora_llama_flash_attention_2_forward_s3_state__r20260714"
TARGET_FILE_SUFFIX = "src/llamafactory/model/model_utils/longlora.py"
TARGET_FUNC = "llamafactory.model.model_utils.longlora.llama_flash_attention_2_forward"
OBSERVED_LINE = 207
OBSERVED_OCCURRENCE = 1
VARIABLES = [
    "attention_mask",
    "dropout_rate",
    "groupsz",
    "input_dtype",
    "num_groups",
    "target_dtype",
]

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<path>.+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
    r"(?: .*?)? locals=(?P<locals>\{.*\})$"
)


def _parse_trace(trace_path: Path) -> list[dict]:
    if not trace_path.exists():
        raise RuntimeError(f"Trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"Trace log is empty: {trace_path}")

    events = []
    for raw_line in text.splitlines():
        match = LINE_RE.match(raw_line)
        if not match:
            continue
        groups = match.groupdict()
        try:
            locals_dict = ast.literal_eval(groups["locals"])
        except Exception as exc:  # pragma: no cover - hard failure path
            raise RuntimeError(f"Failed to parse locals from line: {raw_line}") from exc

        if not isinstance(locals_dict, dict):
            raise RuntimeError(f"Locals payload is not a dict: {raw_line}")

        events.append(
            {
                "path": groups["path"].replace("\\", "/"),
                "lineno": int(groups["lineno"]),
                "func": groups["func"],
                "event": groups["event"],
                "locals": locals_dict,
            }
        )
    return events


def _first_invocation_events(all_events: list[dict]) -> list[dict]:
    target_events = [
        e
        for e in all_events
        if e["func"] == TARGET_FUNC and e["path"].endswith(TARGET_FILE_SUFFIX)
    ]
    if not target_events:
        raise RuntimeError("Trace contains zero events for target function.")

    started = False
    invocation = []
    depth = 0
    for event in target_events:
        if event["event"] == "call":
            if not started:
                started = True
                depth = 1
                invocation.append(event)
            else:
                depth += 1
                invocation.append(event)
            continue

        if started:
            invocation.append(event)
            if event["event"] == "return":
                depth -= 1
                if depth == 0:
                    break

    if not invocation:
        raise RuntimeError("Could not isolate first invocation for target function.")

    return invocation


def _state_after_line(invocation_events: list[dict]) -> dict:
    state: dict[str, str] = {}
    seen = 0
    capture_next = False

    for event in invocation_events:
        state.update(event["locals"])
        if capture_next:
            return dict(state)

        if event["event"] == "line" and event["lineno"] == OBSERVED_LINE:
            seen += 1
            if seen == OBSERVED_OCCURRENCE:
                capture_next = True

    raise RuntimeError(
        f"Did not observe state immediately after line {OBSERVED_LINE} "
        f"execution #{OBSERVED_OCCURRENCE}."
    )


def _build_question() -> str:
    return (
        "During execution of test file "
        "`llama_factory_qa/longlora_llama_flash_attention_2_forward_s3_state__r20260714/files/testcase.py`, "
        "test class `TestLongLoraFlashAttention2ForwardState`, test method "
        "`test_shift_mask_and_dtype_branch_state`, consider the first invocation of "
        "`llamafactory.model.model_utils.longlora.llama_flash_attention_2_forward` "
        "defined in `src/llamafactory/model/model_utils/longlora.py`. "
        "Let 'line execution count' mean counting only `line` events for this function body. "
        "What are the Python `repr` strings of locals `attention_mask`, `dropout_rate`, `groupsz`, "
        "`input_dtype`, `num_groups`, and `target_dtype` immediately after line 207 has executed for "
        "the 1st time in that invocation? Return JSON with exactly one top-level key "
        "`observed_state`, whose value is a list of objects with keys `variable` (str) and `value` (str), "
        "sorted by `variable` in ascending ASCII lexicographic order (no ties expected)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    trace_path = Path(args.trace_log)
    out_path = Path(args.out)

    events = _parse_trace(trace_path)
    invocation = _first_invocation_events(events)
    observed_state = _state_after_line(invocation)

    missing = [name for name in VARIABLES if name not in observed_state]
    if missing:
        raise RuntimeError(f"Missing expected variables at observation point: {missing}")

    observed_rows = [{"variable": name, "value": observed_state[name]} for name in sorted(VARIABLES)]
    payload = {
        "question_kind": "S3_ProgramState",
        "question": _build_question(),
        "template_answer": {
            "observed_state": [
                {"variable": "str", "value": "str"},
            ]
        },
        "oracle_answer": {"observed_state": observed_rows},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote oracle for {INSTANCE_ID} to {out_path}")


if __name__ == "__main__":
    main()
