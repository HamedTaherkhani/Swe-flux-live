#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/train/ppo/trainer.py"
TARGET_FUNC = "llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train"
TRACKED_FUNCS = {
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.batched_forward_pass",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.create_optimizer",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.get_inputs",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.get_rewards",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train",
    "llamafactory.train.ppo.trainer.CustomPPOTrainer.save_model",
}
TRACE_NAME_TO_FUNC = {func.rpartition(".")[2]: func for func in TRACKED_FUNCS}

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/trainer_ppo_train_m6_calls/files/testcase.py::"
    "TestIndirectPPOTrainingCallGraph::test_seeded_workflow_training`. The primary target is "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train` in "
    "`src/llamafactory/train/ppo/trainer.py`. Report `covered_functions` for exactly this tracked "
    "set: `llamafactory.train.ppo.trainer.CustomPPOTrainer.batched_forward_pass`, "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.create_optimizer`, "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.get_inputs`, "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.get_rewards`, "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.ppo_train`, and "
    "`llamafactory.train.ppo.trainer.CustomPPOTrainer.save_model`, all defined in that same file. "
    "A tracked function is covered if Python emits at least one `call` event for its exact runtime "
    "function identity anywhere during the complete test run. Count calls regardless of whether "
    "they are direct calls from the target frame, nested or transitive calls while the target is "
    "on the stack, or calls made before or after the target frame by the workflow; calls to "
    "functions outside the listed set are irrelevant. Repeated calls and recursive calls still "
    "produce only one output object for that function: deduplicate by exact function identity. A "
    "generator or coroutine resumption contributes coverage only when Python emits a `call` event "
    "for that exact tracked function, and repeated resumptions do not add duplicate objects. "
    "Function identity is the full runtime dotted `module.Class.method` or `module.function` "
    "qualname (for example, `pkg.worker.Engine.run`). Emit only covered members; do not emit an "
    "object or placeholder for an uncovered member. Sort the deduplicated objects in ascending "
    "lexicographic order by the two-key tuple (`file`, `func`), comparing the complete JSON string "
    "values by Unicode code-point order; this tuple is also the complete tie-break rule. For every "
    "object, `file` is the POSIX repo-relative source path with no leading `./` (for example, "
    "`pkg/worker.py`), and `func` is the dotted identity just defined. Return exactly one JSON "
    "object with the single key `covered_functions`; its value is a JSON array whose elements each "
    "have exactly two JSON string fields, `file` and `func`. There is no invocation numbering or "
    "chronological ordering in the answer after set deduplication. No `repr`/`str` value formatting, "
    "exception-name convention, null convention, or line-number convention applies because every "
    "answer leaf is a source-path or function-identity JSON string."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/train/ppo/trainer\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def read_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match:
            trace_func = match.group("func")
            code_name = trace_func.rpartition(".")[2]
            canonical_func = TRACE_NAME_TO_FUNC.get(code_name)
            if canonical_func is not None:
                events.append((canonical_func, match.group("event")))
    return events


def compute_covered(events):
    target_events = [event for func, event in events if func == TARGET_FUNC]
    if not target_events:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if "call" not in target_events:
        fail(f"trace contains zero call events for target function {TARGET_FUNC}")

    called = {func for func, event in events if event == "call" and func in TRACKED_FUNCS}
    if not called:
        fail("computed covered function set is empty")
    return sorted(
        ({"file": TARGET_FILE, "func": func} for func in called),
        key=lambda item: (item["file"], item["func"]),
    )


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = read_events(trace_path)
    if not events:
        fail("trace contains zero matching events in the target file")

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_functions": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"covered_functions": compute_covered(events)},
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
