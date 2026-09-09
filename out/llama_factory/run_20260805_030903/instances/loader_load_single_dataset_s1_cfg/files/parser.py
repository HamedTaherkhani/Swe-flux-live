import argparse
import json
import os
import re
import sys


QUESTION_TEXT = (
    "Run only `llama_factory_qa/loader_load_single_dataset_s1_cfg/files/testcase.py::"
    "TestLoadSingleDatasetS1CFG::test_cfg_second_invocation_line_sequence`. "
    "For the function `src.llamafactory.data.loader._load_single_dataset` defined in "
    "`src/llamafactory/data/loader.py`, count invocations as 1-based in chronological order "
    "of that function's call entries during this test method. For invocation 2 only, list the "
    "exact executed source line numbers from this function body in temporal order, using only "
    "line-execution steps of this function (exclude call/return/exception records), and keep "
    "duplicates whenever the same line executes multiple times. Return exactly one JSON object "
    "with key `executed_line_sequence` of type `array<int>` preserving that temporal order "
    "(no deduplication, no re-sorting)."
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    trace_path = args.trace_log
    out_path = args.out

    if not os.path.exists(trace_path):
        raise FileNotFoundError(f"Trace log not found: {trace_path}")
    if os.path.getsize(trace_path) == 0:
        raise RuntimeError(f"Trace log is empty: {trace_path}")

    target_suffix = "/src/llamafactory/data/loader.py"
    target_func = "src.llamafactory.data.loader._load_single_dataset"
    event_re = re.compile(r"^\S+\s+\S+\s+(.+?):(\d+)\s+(\S+)\s+event=(\w+)\b")

    total_target_events = 0
    invocation_count = 0
    active_invocation = None
    second_invocation_lines = []

    with open(trace_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            match = event_re.match(line)
            if not match:
                continue

            file_path, lineno_s, func_name, event = match.groups()
            normalized_file = file_path.replace("\\", "/")
            if not normalized_file.endswith(target_suffix):
                continue
            if func_name != target_func:
                continue

            total_target_events += 1
            lineno = int(lineno_s)

            if event == "call":
                invocation_count += 1
                active_invocation = invocation_count
                continue

            if event in {"return", "exception"}:
                if active_invocation is not None:
                    active_invocation = None
                continue

            if event == "line" and active_invocation == 2:
                second_invocation_lines.append(lineno)

    if total_target_events == 0:
        raise RuntimeError("Trace contains zero events for src.llamafactory.data.loader._load_single_dataset.")
    if invocation_count < 2:
        raise RuntimeError(f"Expected at least 2 invocations, found {invocation_count}.")
    if not second_invocation_lines:
        raise RuntimeError("No line events captured for invocation 2.")

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION_TEXT,
        "template_answer": {"executed_line_sequence": ["int"]},
        "oracle_answer": {"executed_line_sequence": second_invocation_lines},
    }

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        handle.write("\n")

    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
