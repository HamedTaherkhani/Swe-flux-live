#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any


TARGET_FILE_SUFFIX = "/src/llamafactory/data/processor/supervised.py"
TARGET_FUNC_SUFFIX = ".preprocess_dataset"
TARGET_CALL_LINE = 127
OBSERVATION_LINE = 170
TARGET_FUNC_START = 127
TARGET_FUNC_END = 203

PREDICATES = [
    "i < len(knapsack)",
    "len(packed_input_ids) == len(packed_labels)",
    "length in knapsack",
    "len(knapsack) == 2",
    "i == 0",
    "len(packed_input_ids) % length == 0",
    "length != 5",
    "sum(knapsack) <= 7",
]

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build M7 invariant oracle from trace.")
    parser.add_argument("--trace-log", required=True, help="Path to trace log")
    parser.add_argument("--out", required=True, help="Path to output oracle json")
    return parser.parse_args()


def read_trace_lines(trace_log: Path) -> list[str]:
    if not trace_log.exists():
        raise SystemExit(f"Trace log not found: {trace_log}")
    if trace_log.stat().st_size == 0:
        raise SystemExit(f"Trace log is empty: {trace_log}")
    lines = [line for line in trace_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"Trace log has no non-empty lines: {trace_log}")
    return lines


def _parse_locals_blob(raw_line: str) -> dict[str, str]:
    marker = " locals="
    idx = raw_line.find(marker)
    if idx == -1:
        return {}
    locals_blob = raw_line[idx + len(marker) :].strip()
    try:
        parsed = ast.literal_eval(locals_blob)
    except Exception as exc:
        raise SystemExit(f"Failed to parse locals payload: {locals_blob!r} ({exc})") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"Locals payload is not a dict: {locals_blob!r}")
    return parsed


def _literal_from_repr(locals_payload: dict[str, str], key: str) -> Any:
    if key not in locals_payload:
        raise SystemExit(f"Missing local variable {key!r} at observation line {OBSERVATION_LINE}.")
    raw_repr = locals_payload[key]
    try:
        return ast.literal_eval(raw_repr)
    except Exception as exc:
        raise SystemExit(f"Failed to parse repr for local {key!r}: {raw_repr!r} ({exc})") from exc


def collect_observations(trace_lines: list[str]) -> list[dict[str, Any]]:
    target_event_count = 0
    invocation_count = 0
    active_stack: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    for raw_line in trace_lines:
        match = TRACE_RE.match(raw_line)
        if match is None:
            continue

        file_path = match.group("file").replace("\\", "/")
        func_name = match.group("func")
        if not file_path.endswith(TARGET_FILE_SUFFIX):
            continue
        if not func_name.endswith(TARGET_FUNC_SUFFIX):
            continue

        event = match.group("event")
        lineno = int(match.group("lineno"))

        if event == "call":
            if lineno != TARGET_CALL_LINE:
                continue
            target_event_count += 1
            invocation_count += 1
            active_stack.append({"invocation_index": invocation_count, "locals": _parse_locals_blob(raw_line)})
            continue

        if lineno < TARGET_FUNC_START or lineno > TARGET_FUNC_END:
            continue
        target_event_count += 1

        if not active_stack:
            raise SystemExit("Malformed trace: observed target event without active invocation.")

        current = active_stack[-1]
        invocation_index = current["invocation_index"]
        current["locals"].update(_parse_locals_blob(raw_line))
        if event == "line" and lineno == OBSERVATION_LINE:
            locals_payload = _parse_locals_blob(raw_line)
            merged_locals = dict(current["locals"])
            merged_locals.update(locals_payload)
            observation = {
                "invocation_index": invocation_index,
                "i": _literal_from_repr(merged_locals, "i"),
                "length": _literal_from_repr(merged_locals, "length"),
                "knapsack": _literal_from_repr(merged_locals, "knapsack"),
                "packed_input_ids": _literal_from_repr(merged_locals, "packed_input_ids"),
                "packed_labels": _literal_from_repr(merged_locals, "packed_labels"),
            }
            observations.append(observation)
        elif event in {"return", "exception"}:
            active_stack.pop()

    if target_event_count == 0:
        raise SystemExit(
            "Trace contains zero events for target function PackedSupervisedDatasetProcessor.preprocess_dataset."
        )
    if invocation_count == 0:
        raise SystemExit("Trace did not include any call events for target function.")
    if active_stack:
        raise SystemExit("Malformed trace: unterminated target function invocation in trace.")
    return observations


def evaluate_predicate(predicate: str, obs: dict[str, Any]) -> bool:
    i = obs["i"]
    knapsack = obs["knapsack"]
    length = obs["length"]
    packed_input_ids = obs["packed_input_ids"]
    packed_labels = obs["packed_labels"]

    if predicate == "i < len(knapsack)":
        return i < len(knapsack)
    if predicate == "len(packed_input_ids) == len(packed_labels)":
        return len(packed_input_ids) == len(packed_labels)
    if predicate == "length in knapsack":
        return length in knapsack
    if predicate == "len(knapsack) == 2":
        return len(knapsack) == 2
    if predicate == "i == 0":
        return i == 0
    if predicate == "len(packed_input_ids) % length == 0":
        return len(packed_input_ids) % length == 0
    if predicate == "length != 5":
        return length != 5
    if predicate == "sum(knapsack) <= 7":
        return sum(knapsack) <= 7
    raise SystemExit(f"Unsupported predicate: {predicate}")


def build_invariant_results(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for predicate in sorted(PREDICATES):
        held = True
        first_violation_invocation = None
        if not observations:
            held = False
        else:
            for obs in observations:
                if not evaluate_predicate(predicate, obs):
                    held = False
                    first_violation_invocation = obs["invocation_index"]
                    break
        results.append(
            {
                "predicate": predicate,
                "held": held,
                "first_violation_invocation": first_violation_invocation,
            }
        )
    return results


def build_question() -> str:
    return (
        "For pytest test `llama_factory_qa/supervised_preprocess_dataset_m7_invariants__r20260714/files/testcase.py::"
        "TestPackedSupervisedPreprocessDatasetM7Invariants::test_invariants_on_inner_packing_loop`, analyze "
        "`src.llamafactory.data.processor.supervised.PackedSupervisedDatasetProcessor.preprocess_dataset` "
        "in file `src/llamafactory/data/processor/supervised.py`. "
        "Observe the loop at line 169 (`for i, length in enumerate(knapsack):`) and define one observation as each "
        "execution of the first loop-body line 170 (`index = length2indexes[length].pop()`), using local-variable "
        "values at that line event before line 170 executes. Invocation indices are 1-based by dynamic entry order "
        "into `preprocess_dataset` during this test method. A predicate \"held\" means it evaluated to true at every "
        "observation across all invocations. If there are zero observations, treat each predicate as vacuous by "
        "reporting `held` as false and `first_violation_invocation` as null. "
        "Evaluate exactly these candidate predicates verbatim: "
        "`i < len(knapsack)`; `len(packed_input_ids) == len(packed_labels)`; `length in knapsack`; "
        "`len(knapsack) == 2`; `i == 0`; `len(packed_input_ids) % length == 0`; `length != 5`; `sum(knapsack) <= 7`. "
        "Return JSON with exactly one top-level key `invariant_results` (array), sorted by `predicate` ascending "
        "lexicographic order. Each element must have keys `predicate` (str), `held` (bool), and "
        "`first_violation_invocation` (int|null)."
    )


def main() -> None:
    args = parse_args()
    trace_lines = read_trace_lines(Path(args.trace_log))
    observations = collect_observations(trace_lines)
    invariant_results = build_invariant_results(observations)

    payload = {
        "question_kind": "M7_Invariants",
        "question": build_question(),
        "template_answer": {
            "invariant_results": [
                {"predicate": "str", "held": "bool", "first_violation_invocation": "int|null"}
            ]
        },
        "oracle_answer": {"invariant_results": invariant_results},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["oracle_answer"], sort_keys=True, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[parser-error] {exc}", file=sys.stderr)
        raise
