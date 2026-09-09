import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/stat_utils/cal_mfu.py"
TARGET_FUNC = "scripts.stat_utils.cal_mfu.compute_model_flops"
OBSERVATION_LINE = 73
VARIABLES = (
    "attn_proj_flops",
    "embedding_coeff",
    "embedding_flops",
    "mlp_flops",
    "non_embedding_coeff",
    "non_embedding_flops",
    "sdpa_flops",
)

QUESTION = """Run only the pytest test `llama_factory_qa/cal_mfu_compute_model_flops_s3_state/files/testcase.py::TestCalculateMFUState::test_calculate_multiple_generated_models`. During that test run, consider the exact function `scripts.stat_utils.cal_mfu.compute_model_flops` in the repository-relative file `scripts/stat_utils/cal_mfu.py`.

For the first invocation of that function, report the values of the seven locals `attn_proj_flops`, `embedding_coeff`, `embedding_flops`, `mlp_flops`, `non_embedding_coeff`, `non_embedding_flops`, and `sdpa_flops` immediately after line 73 has executed for the first time. An invocation is one call of this exact function during the test run, numbered from 1 in chronological order. “Immediately after line 73 has executed” means after the augmented assignment beginning on that line has read the prior value, computed and stored the updated value, with the frame's locals as they stand before the next source line executes. Thus the augmented assignment is treated as both a read and a write, and the requested state includes its completed write.

Line numbers are absolute 1-based line numbers in the named file as it exists in the repository. For a multi-line statement or expression, execution is attributed to the line where that statement or expression begins. Decorator lines, the `def` line, the docstring line, comments, and blank lines do not count as executions of line 73. If the specified line were not reached, the task would have no answer; in this test it is reached and all seven named locals exist at the observation point.

Return exactly `{"observed_state": [...]}`. The list must contain exactly one object for each named local, and each object must have exactly the two string keys `value` and `variable`. Sort the objects by `variable` in ascending Unicode code-point order, with no deduplication. Set `variable` to the exact source-level local name. Set `value` to Python's `repr()` string for that local's value at the observation point. For a container, use `repr()` of the whole container rather than separately serializing its elements: strings retain their quotes, and `None`, `True`, and `False` use Python spellings inside the value string. For example, a hypothetical tuple containing a label and no value has decoded JSON-string content `('sample', None)`. If a represented string contains an embedded newline, the decoded JSON string contains a real newline, escaped as required in the JSON file. No JSON null, empty-string sentinel, or omitted key is used for a missing value."""

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)"
    r".* locals=(?P<locals>\{.*\})$"
)


def fail(message):
    raise RuntimeError(message)


def parse_trace(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for log_line_number, raw_line in enumerate(text.splitlines(), 1):
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse locals on trace-log line {log_line_number}: {exc}")
        if not isinstance(changed_locals, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed_locals.items()
        ):
            fail(f"malformed locals mapping on trace-log line {log_line_number}")
        target_events.append(
            {
                "event": match.group("event"),
                "line": int(match.group("line")),
                "locals": changed_locals,
            }
        )

    if not target_events:
        fail(f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}")

    invocation = 0
    active = False
    state = {}
    pending_observation = False
    observation_hits = 0
    observed = None

    for event in target_events:
        if event["event"] == "call":
            invocation += 1
            active = invocation == 1
            state = {}
            pending_observation = False

        if not active:
            continue

        state.update(event["locals"])
        if pending_observation:
            observed = dict(state)
            break

        if event["event"] == "line" and event["line"] == OBSERVATION_LINE:
            observation_hits += 1
            if observation_hits == 1:
                pending_observation = True

        if event["event"] in {"return", "exception"}:
            active = False

    if observed is None:
        fail(
            f"did not find an event immediately after the first execution of "
            f"line {OBSERVATION_LINE} in invocation 1"
        )

    missing = sorted(set(VARIABLES) - observed.keys())
    if missing:
        fail(f"observation is missing required locals: {missing}")

    return {
        "observed_state": [
            {"value": observed[variable], "variable": variable}
            for variable in sorted(VARIABLES)
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {args.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
