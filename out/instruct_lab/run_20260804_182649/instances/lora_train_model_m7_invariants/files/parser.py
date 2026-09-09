#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/train/lora_mlx/lora.py"
TARGET_FUNC = "instructlab.train.lora_mlx.lora.train_model"
OBSERVATION_LINE = 172
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b.*? locals=(?P<locals>\{.*\})$"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_locals(text: str, trace_line: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals on trace line {trace_line}: {exc}")
    if not isinstance(value, dict):
        fail(f"locals on trace line {trace_line} are not a dictionary")
    if not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        fail(f"locals on trace line {trace_line} do not map strings to repr strings")
    return value


def decode_local(name: str, state: dict[str, str], trace_line: int):
    if name not in state:
        fail(f"local {name!r} is absent at observation on trace line {trace_line}")
    try:
        return ast.literal_eval(state[name])
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot decode local {name!r} on trace line {trace_line}: {exc}")


def compute_answer(trace_path: Path) -> dict[str, bool | int]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    frame_state: dict[str, str] = {}
    outcomes: list[bool] = []

    for trace_line, raw_line in enumerate(text.splitlines(), start=1):
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        changed = parse_locals(match.group("locals"), trace_line)
        if event == "call":
            target_calls += 1
            frame_state = {}
        frame_state.update(changed)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            n_tokens = decode_local("n_tokens", frame_state, trace_line)
            losses = decode_local("losses", frame_state, trace_line)
            if not isinstance(n_tokens, int):
                fail(f"n_tokens is not an int at observation on trace line {trace_line}")
            if not isinstance(losses, list):
                fail(f"losses is not a list at observation on trace line {trace_line}")
            outcomes.append(n_tokens % 92 >= len(losses))

        if event in {"return", "exception"}:
            frame_state = {}

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for target function {TARGET_FUNC}")

    total = len(outcomes)
    violations = sum(not outcome for outcome in outcomes)
    return {
        "is_invariant_always_held": total > 0 and violations == 0,
        "total_iterations_observed": total,
        "violating_iteration_count": violations,
    }


def build_question() -> str:
    return (
        "Run the pytest test "
        "`instruct_lab_qa/lora_train_model_m7_invariants/files/testcase.py::"
        "TestGeneratedLoraTraining::test_seeded_training_state` against this "
        "repository. Consider every invocation of exactly "
        "`instructlab.train.lora_mlx.lora.train_model` in "
        "`src/instructlab/train/lora_mlx/lora.py` during the complete named test "
        "run. An invocation is one runtime call of exactly that function, numbered "
        "1-based in chronological order from the start of the test; calls to its "
        "caller, callees, builtins, callable objects, comprehension frames, and "
        "generator frames are excluded. Within those invocations, an observed "
        "iteration is each execution by the target function's own frame of physical "
        "line 172, the line whose statement begins `if (it + 1) % "
        "steps_per_report == 0:`. Iteration N is the Nth such line execution across "
        "all target invocations in chronological order, starting at 1. At each "
        "observation, use the target frame's live local values immediately before "
        "the line-172 statement executes and evaluate this candidate predicate "
        "verbatim: `n_tokens % 92 >= len(losses)`. Use ordinary Python integer "
        "modulo, comparison, and `len` semantics. `losses` is the current local list "
        "as a whole, without conversion, sorting, or deduplication. The predicate "
        "holds for an observation exactly when that Python expression evaluates to "
        "`True`, and it violates the predicate when the expression evaluates to "
        "`False`. Line numbers are absolute, 1-based physical lines in the named "
        "repository file as it exists for this test. For a multi-line statement, an "
        "executed-line event belongs to the physical line where that statement or "
        "expression begins. The `def` line is call entry rather than an observed "
        "line here; decorator and docstring lines are not observation points. "
        "Preserve every qualifying observation in chronological order while "
        "evaluating, with no filtering after the file/function/event/line rules, no "
        "sorting, and no deduplication; because the output contains only aggregate "
        "counts, no ordering tie-breaker applies. Return exactly one JSON object "
        "with keys in this order: `is_invariant_always_held`, "
        "`total_iterations_observed`, and `violating_iteration_count`. The first "
        "value is a native JSON boolean and is true only if the predicate held at "
        "every observed iteration. The other two values are native JSON integers: "
        "respectively the number of observed iterations and the number among them "
        "that violated the predicate. Do not encode any value using `repr()`, a "
        "JSON string, JSON null, an empty string, or an omitted key. If there are "
        "zero observed iterations, the invariant is not evaluable: report the "
        "boolean as false and both integer counts as zero."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M7_Invariants",
        "question": build_question(),
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": compute_answer(Path(args.trace_log)),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
