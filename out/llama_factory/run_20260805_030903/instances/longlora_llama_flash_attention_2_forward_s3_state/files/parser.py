#!/usr/bin/env python3
import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FUNC = "llamafactory.model.model_utils.longlora.llama_flash_attention_2_forward"
OBSERVATION_LINE = 238
VARIABLES = ("attention_mask", "attn_output", "key_states", "query_states")

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/longlora_llama_flash_attention_2_forward_s3_state/files/testcase.py::"
    "TestGeneratedFlashAttentionState::test_shifted_attention_through_pipeline`. Consider the "
    "first invocation of `llamafactory.model.model_utils.longlora.llama_flash_attention_2_forward` "
    "in `src/llamafactory/model/model_utils/longlora.py`. An invocation is one runtime `call` of "
    "that exact function during the complete test run, numbered 1-based in chronological order. "
    "Report the values of the four named locals immediately after the multi-line assignment "
    "statement whose expression begins at absolute, 1-based source line 230 has executed for the "
    "first time in that invocation—that is, after the entire `torch.cat(...)` assignment spanning "
    "lines 230-236 has completed and immediately before the statement beginning at line 238 "
    "executes. For multi-line statements, associate execution with the absolute, 1-based line where "
    "the statement or expression begins; continuation lines, the `def` line, decorators, and "
    "comments do not define additional observation points. Return exactly one JSON "
    "object with key `observed_state`. Its value is a JSON array of exactly four objects, in this "
    "fixed order: `attention_mask`, `attn_output`, `key_states`, then `query_states`; do not sort, "
    "deduplicate, or omit entries. Every object has exactly two keys: `value`, a JSON string, and "
    "`variable`, a JSON string containing the local's bare name. Emit object keys as shown by the "
    "answer schema; JSON object key order itself is semantically irrelevant. Each `value` is the "
    "ordinary Python `repr()` of the complete runtime value at that observation point under the "
    "print options established by the test. For each tensor this means the `repr()` of the whole "
    "tensor container, not recursive JSON conversion: strings retain quotes, `None`/`True`/`False` "
    "would use Python spellings, dtype or gradient annotations are retained when `repr()` includes "
    "them, and embedded newlines appear as real newline characters in the decoded JSON string "
    "(escaped as required in serialized JSON). For example, an unrelated string value would be "
    "encoded as the JSON string `\"'sample'\"`. No reported value is represented by an empty "
    "string, JSON null, or an absent key."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/model/model_utils/longlora\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.*?"
    r"locals=(?P<locals>\{.*\})$"
)


def parse_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_locals(raw_locals, trace_line_number):
    try:
        parsed = ast.literal_eval(raw_locals)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals at trace line {trace_line_number}: {exc}")
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
    ):
        fail(f"locals at trace line {trace_line_number} are not a string-to-string dictionary")
    return parsed


def main():
    args = parse_cli()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for trace_line_number, raw_line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                (
                    match.group("event"),
                    int(match.group("line")),
                    parse_locals(match.group("locals"), trace_line_number),
                )
            )

    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    invocation_number = 0
    active = False
    state = {}
    observed = None
    completed = False

    for event, source_line, changed_locals in events:
        if event == "call":
            invocation_number += 1
            active = invocation_number == 1
            state = dict(changed_locals) if active else {}
            continue
        if not active:
            continue

        state.update(changed_locals)
        if event == "line" and source_line == OBSERVATION_LINE:
            if observed is not None:
                fail("observation line executed more than once in the first invocation")
            missing = [name for name in VARIABLES if name not in state]
            if missing:
                fail(f"locals missing at observation point: {missing}")
            observed = [{"value": state[name], "variable": name} for name in VARIABLES]

        if event == "exception":
            fail("first invocation raised before completing")
        if event == "line" and source_line == 244:
            completed = True
            break

    if not completed:
        fail("first invocation did not reach its return statement")
    if observed is None:
        fail(f"first invocation never reached observation line {OBSERVATION_LINE}")

    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {"observed_state": [{"value": "str", "variable": "str"}]},
        "oracle_answer": {"observed_state": observed},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
