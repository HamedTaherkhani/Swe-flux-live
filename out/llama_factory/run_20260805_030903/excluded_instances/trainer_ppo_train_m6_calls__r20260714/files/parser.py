import argparse
import json
import re
import sys
from pathlib import Path


TRACE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} (?P<path>[^:]+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

TRACED_FUNCTIONS = [
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.batched_forward_pass",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.get_inputs",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.get_rewards",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.save_model",
]

TARGET_FUNCTION = "llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train"

SHORT_NAME_TO_CANONICAL = {
    name.rsplit(".", 1)[-1]: name for name in TRACED_FUNCTIONS
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse trace log into oracle JSON.")
    parser.add_argument("--trace-log", required=True, help="Path to trace log file.")
    parser.add_argument("--out", required=True, help="Path to output oracle JSON file.")
    return parser.parse_args()


def load_trace_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Trace log not found: {path}")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"Trace log is empty: {path}")
    return [line for line in content.splitlines() if line.strip()]


def compute_call_frequencies(lines: list[str]) -> list[dict]:
    counts = {name: 0 for name in TRACED_FUNCTIONS}
    first_caller = {name: None for name in TRACED_FUNCTIONS}
    stack: list[str] = []
    parsed_any = False
    target_event_count = 0

    for line in lines:
        match = TRACE_PATTERN.match(line)
        if not match:
            continue

        parsed_any = True
        raw_func = match.group("func")
        event = match.group("event")
        short_name = raw_func.rsplit(".", 1)[-1]
        func = SHORT_NAME_TO_CANONICAL.get(short_name)

        if func is None:
            continue

        if func == TARGET_FUNCTION:
            target_event_count += 1

        if event == "call":
            caller = stack[-1] if stack else "<external>"
            counts[func] += 1
            if first_caller[func] is None:
                first_caller[func] = caller
            stack.append(func)
        elif event == "return":
            if stack and stack[-1] == func:
                stack.pop()
            elif func in stack:
                while stack and stack[-1] != func:
                    stack.pop()
                if stack and stack[-1] == func:
                    stack.pop()

    if not parsed_any:
        raise ValueError("Trace log has no parseable trace events.")
    if target_event_count == 0:
        raise ValueError(
            f"Trace log contains zero events for target function {TARGET_FUNCTION}."
        )

    rows = []
    for function_name in sorted(TRACED_FUNCTIONS):
        rows.append(
            {
                "function": function_name,
                "count": counts[function_name],
                "first_caller": first_caller[function_name],
            }
        )
    return rows


def build_question() -> str:
    return (
        "For pytest test "
        "`llama_factory_qa/trainer_ppo_train_m6_calls__r20260714/files/testcase.py::"
        "TestPPOTrainM6Calls::test_call_frequency_and_first_caller`, analyze runtime calls rooted at "
        "`llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train` in file "
        "`src/llamafactory/train/ppo/trainer.py`. "
        "Use only this traced function set: "
        "[`llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train`, "
        "`llamafactory.train.ppo.trainer.CustomPPOTrainer.get_inputs`, "
        "`llamafactory.train.ppo.trainer.CustomPPOTrainer.get_rewards`, "
        "`llamafactory.train.ppo.trainer.CustomPPOTrainer.save_model`, "
        "`llamafactory.train.ppo.trainer.CustomPPOTrainer.batched_forward_pass`]. "
        "A function invocation means one dynamic `call` event for that exact dotted qualname. "
        "For each function in the set, report: "
        "(1) `count`: total number of its invocations during the whole test; "
        "(2) `first_caller`: the dotted qualname at the top of the traced-call stack when its first `call` occurs, "
        "or `\"<external>\"` if the stack is empty, or `null` when `count` is 0. "
        "Return JSON with key `call_frequencies` (array of objects), each object having keys "
        "`function` (str), `count` (int), and `first_caller` (str|null). "
        "Sort rows by `function` ascending lexicographic order."
    )


def main() -> int:
    args = parse_args()
    trace_path = Path(args.trace_log)
    out_path = Path(args.out)

    lines = load_trace_lines(trace_path)
    call_frequencies = compute_call_frequencies(lines)

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {
            "call_frequencies": [
                {"function": "str", "count": "int", "first_caller": "str|null"}
            ]
        },
        "oracle_answer": {"call_frequencies": call_frequencies},
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[parser-error] {exc}", file=sys.stderr)
        raise
