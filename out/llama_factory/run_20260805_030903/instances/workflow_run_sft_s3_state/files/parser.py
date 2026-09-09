import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/llamafactory/train/sft/workflow.py"
TARGET_FUNC = "llamafactory.train.sft.workflow.run_sft"
OBSERVATION_LINE = 130
VARIABLES = (
    "gen_kwargs",
    "metric_module",
    "metrics",
    "predict_results",
    "train_result",
)

QUESTION = """Run only the pytest test `llama_factory_qa/workflow_run_sft_s3_state/files/testcase.py::TestSFTWorkflowState::test_public_training_entrypoint`. During that test run, consider `llamafactory.train.sft.workflow.run_sft` in the repository-relative file `src/llamafactory/train/sft/workflow.py`.

For the first invocation of that function, report the values of the five locals `gen_kwargs`, `metric_module`, `metrics`, `predict_results`, and `train_result` immediately after line 130 has executed for the first time. Here, an invocation is one `call` of this exact function during the test run, numbered from 1 in chronological order. “Immediately after line 130 has executed” means after the `trainer.save_predictions(...)` call beginning on that line has returned, with the frame's locals as they stand before the next source line executes.

Line numbers are absolute 1-based line numbers in the named file as it exists in the repository. For any multi-line statement, its execution event belongs to the line on which the statement or expression begins; decorator lines, the `def` line, and non-executed comment or blank lines are not candidate observation points here.

Return exactly `{"observed_state": [...]}`. The list must contain exactly one object for each named local, each object having exactly the two string keys `value` and `variable`. Sort the objects by `variable` in ascending Unicode code-point order; do not deduplicate them. Set `variable` to the local's exact source-level name. Set `value` to Python's `repr()` string for the value at the observation point. For a container, use `repr()` of the whole container rather than separately serializing its elements: strings therefore retain quotes, and `None`, `True`, and `False` use Python spellings inside the value string. For example, a hypothetical list containing a string and no value would be represented by the JSON string whose decoded content is `['sample', None]`. If a represented string contains a newline, the decoded JSON string contains that newline (with the JSON file using the required JSON escape). All five locals exist at this point, so no missing-value or JSON-null convention applies."""


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
    for line_number, raw_line in enumerate(text.splitlines(), 1):
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
            fail(f"cannot parse locals on trace-log line {line_number}: {exc}")
        if not isinstance(changed_locals, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in changed_locals.items()
        ):
            fail(f"malformed locals mapping on trace-log line {line_number}")
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
    pending_observation = False
    state = {}
    observed = None
    observation_hits = 0

    for event in target_events:
        if event["event"] == "call":
            invocation += 1
            active = invocation == 1
            pending_observation = False
            state = {}

        if not active:
            continue

        state.update(event["locals"])

        if pending_observation:
            observed = dict(state)
            pending_observation = False
            break

        if event["event"] == "line" and event["line"] == OBSERVATION_LINE:
            observation_hits += 1
            if observation_hits == 1:
                pending_observation = True

        if event["event"] in {"return", "exception"}:
            active = False

    if observed is None:
        fail(
            f"did not find an event immediately after the first execution of line "
            f"{OBSERVATION_LINE} in invocation 1"
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
