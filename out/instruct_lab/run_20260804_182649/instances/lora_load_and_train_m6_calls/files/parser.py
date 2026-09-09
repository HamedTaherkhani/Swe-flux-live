#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/train/lora_mlx/lora.py"
MODULE = "instructlab.train.lora_mlx.lora"
TARGET_FUNC = f"{MODULE}.load_and_train"
TRACKED_FUNCS = {
    f"{MODULE}.Dataset.__getitem__",
    f"{MODULE}.Dataset.__init__",
    f"{MODULE}.Dataset.__len__",
    f"{MODULE}.evaluate",
    f"{MODULE}.generate",
    f"{MODULE}.iterate_batches",
    f"{MODULE}.load",
    f"{MODULE}.load.<locals>.load_and_check",
    f"{MODULE}.load_and_train",
    f"{MODULE}.loss",
    f"{MODULE}.train_model",
}
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def compute_covered_functions(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    covered: set[tuple[str, str]] = set()
    target_events = 0
    target_calls = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        file_name = match.group("file").replace("\\", "/")
        if not file_name.endswith("/" + TARGET_FILE):
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                target_calls += 1
        if event == "call" and func in TRACKED_FUNCS:
            covered.add((TARGET_FILE, func))

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains no call event for target function {TARGET_FUNC}")
    if not covered:
        fail("trace contains no call events for the tracked function set")

    return [
        {"file": file_name, "func": func}
        for file_name, func in sorted(covered)
    ]


def build_question() -> str:
    tracked_text = ", ".join(f"`{func}`" for func in sorted(TRACKED_FUNCS))
    return (
        "Run the pytest test "
        "`instruct_lab_qa/lora_load_and_train_m6_calls/files/testcase.py::"
        "TestLoraPublicModelCommand::test_generated_prompt_batch` against this "
        "repository. The primary target is "
        "`instructlab.train.lora_mlx.lora.load_and_train` in "
        "`src/instructlab/train/lora_mlx/lora.py`. Considering the following "
        f"exact tracked function set, which members execute at least once: {tracked_text}? "
        "A tracked function executes if, anywhere during the complete named test run, "
        "Python enters a frame and emits a `call` event whose fully qualified identity "
        "exactly equals that tracked member and whose code is defined in the repo-relative "
        "file `src/instructlab/train/lora_mlx/lora.py`. The caller is irrelevant: direct calls, "
        "transitive calls, and calls made while or outside a primary-target frame all "
        "qualify. Calls to builtins, mocks, callable objects, comprehension frames, "
        "and all functions outside the exact tracked set do not qualify. A function "
        "identity is the executing frame's dotted `module.qualname`, for example "
        "`package.submodule.ExampleClass.example_method`; do not use a bare name and "
        "do not prefix it with `src`. An invocation is one such `call` event, numbered "
        "1-based in chronological order from the beginning of the test. Repeated and "
        "recursive invocations are counted as separate events when deciding whether an "
        "event exists, but the output contains only one entry for that function. Python "
        "generators can emit a call event on first entry and again on later resumptions; "
        "each is an invocation under this rule, but all resumptions are likewise "
        "deduplicated to one coverage entry. Omit every tracked member with zero "
        "qualifying call events. "
        "Return exactly one JSON object with the sole key `covered_functions`. Its "
        "value is a JSON array. Each element is an object with exactly the keys `file` "
        "then `func`, and both values are JSON strings. For every element, `file` is "
        "the repo-relative POSIX path `src/instructlab/train/lora_mlx/lora.py`, and "
        "`func` is the exact fully qualified identity defined above. Deduplicate by "
        "the (`file`, `func`) pair, then sort the array in ascending lexicographic "
        "Unicode-code-point order by `file`, with `func` as the tie-breaker; this "
        "sorted order, not call chronology, is the output order. Use ordinary JSON "
        "serialization and JSON string escaping, not Python `repr`. No reported value "
        "is represented by JSON null, an empty string, or an omitted object key."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": build_question(),
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {
            "covered_functions": compute_covered_functions(Path(args.trace_log))
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
