#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/utils.py"
TARGET_FUNC = "instructlab.utils._analyze_dir"
OBSERVATION_LINE = 887
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
        if match.group("func") != TARGET_FUNC:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith("/" + TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        changed = parse_locals(match.group("locals"), trace_line)
        if event == "call":
            target_calls += 1
            frame_state = {}
        frame_state.update(changed)

        if event == "line" and int(match.group("line")) == OBSERVATION_LINE:
            all_files_sizes = decode_local("all_files_sizes", frame_state, trace_line)
            files = decode_local("files", frame_state, trace_line)
            if not isinstance(all_files_sizes, int):
                fail(
                    f"all_files_sizes is not an int at observation on trace line {trace_line}"
                )
            if not isinstance(files, list):
                fail(f"files is not a list at observation on trace line {trace_line}")
            outcomes.append(all_files_sizes % 29 >= len(files))

        if event in {"return", "exception"}:
            frame_state = {}

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")

    total = len(outcomes)
    violations = sum(not outcome for outcome in outcomes)
    return {
        "is_invariant_always_held": total > 0 and violations == 0,
        "total_iterations_observed": total,
        "violating_iteration_count": violations,
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = compute_answer(Path(args.trace_log))
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/utils_analyze_dir_m7_invariants/files/testcase.py::"
        "TestGeneratedModelDirectoryAnalysis::test_generated_model_forest` against "
        "this repository. Consider every invocation of exactly "
        "`instructlab.utils._analyze_dir` in `src/instructlab/utils.py` during the "
        "entire test run. An invocation is one runtime `call` of exactly that "
        "function, numbered 1-based in chronological execution order; calls to "
        "other functions, including its callers, callees, builtins, and any "
        "comprehension or generator frames, are excluded. Within those invocations, "
        "an observed iteration is each execution by the target function's own frame "
        "of physical line 887, the line whose statement begins "
        "`adjusted_all_sizes, magnitude = convert_bytes_to_proper_mag(...)`. "
        "Iteration N is the Nth such line execution across all target invocations in "
        "chronological order, starting at 1. Outer `os.walk` iterations that take "
        "the `continue` at line 880 and therefore do not reach line 887 are not "
        "observed iterations. At each observation, use the target frame's live local "
        "values immediately before the line-887 statement executes and evaluate the "
        "candidate predicate verbatim: "
        "`all_files_sizes % 29 >= len(files)`. Use ordinary Python integer modulo, "
        "comparison, and `len` semantics; `files` is the current local list as a "
        "whole, with no conversion, sorting, or deduplication. The predicate holds "
        "for an observation exactly when that Python expression evaluates to "
        "`True`; an observation violates it when it evaluates to `False`. Line "
        "numbers are absolute, 1-based physical lines in the named repository file "
        "as it exists for this test. For a multi-line statement, an executed-line "
        "event belongs to the physical line where that statement or expression "
        "begins. The `def` line is call entry rather than an observed line here, and "
        "decorator or docstring lines are not observation points. Preserve all "
        "observations in chronological order while evaluating, with no filtering "
        "after the file/function/event/line rules above, no sorting, and no "
        "deduplication; because only counts are returned, no tie-breaker applies. "
        "Return exactly one JSON object with keys in this order: "
        "`is_invariant_always_held`, `total_iterations_observed`, and "
        "`violating_iteration_count`. The first value is a JSON boolean that is true "
        "only if the predicate held at every observed iteration. The latter two "
        "values are JSON integers: respectively the number of observed iterations "
        "and the number among them that violated the predicate. Values are emitted "
        "as native JSON booleans and integers, not as `repr()` or strings; there are "
        "no null, empty-string, or absent-value sentinels. If there are zero observed "
        "iterations, the invariant is not evaluable: report the boolean as false and "
        "both integer counts as zero."
    )
    payload = {
        "question_kind": "M7_Invariants",
        "question": question,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out_path.write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
