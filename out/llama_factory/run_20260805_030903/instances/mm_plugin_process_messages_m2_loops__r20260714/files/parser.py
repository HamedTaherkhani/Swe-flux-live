#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/data/mm_plugin.py"
TARGET_FUNC_SUFFIX = ".process_messages"
TARGET_CALL_LINES = {683, 684}
TARGET_FUNC_START = 684
TARGET_FUNC_END = 781

IMAGE_OUTER_LOOP_LINE = 738
IMAGE_OUTER_BODY_FIRST_LINE = 739
IMAGE_INNER_LOOP_LINE = 743
IMAGE_INNER_BODY_FIRST_LINE = 744

AUDIO_OUTER_LOOP_LINE = 759
AUDIO_OUTER_BODY_FIRST_LINE = 760
AUDIO_INNER_LOOP_LINE = 764
AUDIO_INNER_BODY_FIRST_LINE = 765

TRACE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>/.+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def read_trace_lines(trace_log: Path) -> list[str]:
    if not trace_log.exists():
        raise SystemExit(f"Trace log not found: {trace_log}")
    if trace_log.stat().st_size == 0:
        raise SystemExit(f"Trace log is empty: {trace_log}")
    lines = trace_log.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SystemExit(f"Trace log has no lines: {trace_log}")
    return lines


def _empty_invocation(invocation_index: int) -> dict:
    return {
        "invocation_index": invocation_index,
        "image_outer_inner_counts": [],
        "audio_outer_inner_counts": [],
    }


def collect_nested_loop_counts(trace_lines: list[str]) -> list[dict]:
    matched_target_events = 0
    invocation_count = 0
    active_stack: list[dict] = []
    invocations: list[dict] = []

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
            if lineno not in TARGET_CALL_LINES:
                continue
            matched_target_events += 1
            invocation_count += 1
            inv_data = _empty_invocation(invocation_count)
            invocations.append(inv_data)
            active_stack.append(inv_data)
            continue

        if lineno < TARGET_FUNC_START or lineno > TARGET_FUNC_END:
            continue
        matched_target_events += 1

        if not active_stack:
            raise SystemExit(
                "Malformed trace: target function line/return/exception event found without an active invocation."
            )

        current = active_stack[-1]
        if event == "line":
            if lineno == IMAGE_OUTER_BODY_FIRST_LINE:
                current["image_outer_inner_counts"].append(0)
            elif lineno == IMAGE_INNER_BODY_FIRST_LINE:
                if not current["image_outer_inner_counts"]:
                    raise SystemExit("Malformed trace: image inner-loop body executed before any image outer iteration.")
                current["image_outer_inner_counts"][-1] += 1
            elif lineno == AUDIO_OUTER_BODY_FIRST_LINE:
                current["audio_outer_inner_counts"].append(0)
            elif lineno == AUDIO_INNER_BODY_FIRST_LINE:
                if not current["audio_outer_inner_counts"]:
                    raise SystemExit("Malformed trace: audio inner-loop body executed before any audio outer iteration.")
                current["audio_outer_inner_counts"][-1] += 1
            continue

        if event in {"return", "exception"}:
            active_stack.pop()
            continue

    if matched_target_events == 0:
        raise SystemExit("Trace contains zero events for target function MiniCPMVPlugin.process_messages.")
    if invocation_count == 0:
        raise SystemExit("Trace did not contain any invocation of MiniCPMVPlugin.process_messages.")
    if active_stack:
        raise SystemExit("Malformed trace: unterminated MiniCPMVPlugin.process_messages invocation.")

    return invocations


def build_oracle_answer(invocations: list[dict]) -> dict:
    mapped = []
    for inv in invocations:
        image_map = [
            {"outer_iteration": idx + 1, "inner_iterations": count}
            for idx, count in enumerate(inv["image_outer_inner_counts"])
        ]
        audio_map = [
            {"outer_iteration": idx + 1, "inner_iterations": count}
            for idx, count in enumerate(inv["audio_outer_inner_counts"])
        ]
        mapped.append(
            {
                "invocation_index": inv["invocation_index"],
                "image_inner_iterations_per_outer": image_map,
                "audio_inner_iterations_per_outer": audio_map,
            }
        )

    return {
        "loop_headers": {
            "image_outer": IMAGE_OUTER_LOOP_LINE,
            "image_inner": IMAGE_INNER_LOOP_LINE,
            "audio_outer": AUDIO_OUTER_LOOP_LINE,
            "audio_inner": AUDIO_INNER_LOOP_LINE,
        },
        "invocations": mapped,
    }


def main() -> None:
    args = parse_args()
    trace_lines = read_trace_lines(Path(args.trace_log))
    invocations = collect_nested_loop_counts(trace_lines)
    oracle_answer = build_oracle_answer(invocations)

    oracle = {
        "question_kind": "M2_Loops",
        "question": (
            "During execution of pytest test "
            "`llama_factory_qa/mm_plugin_process_messages_m2_loops__r20260714/files/testcase.py::"
            "TestMiniCPMVProcessMessagesM2Loops::test_nested_loop_iteration_map_across_invocations`, "
            "analyze `src.llamafactory.data.mm_plugin.MiniCPMVPlugin.process_messages` in "
            "`src/llamafactory/data/mm_plugin.py`. Use invocation order defined as 1-based order of entries into "
            "`process_messages` during that test run. Focus on nested loop pairs with headers at lines 738/743 "
            "(image loop pair) and 759/764 (audio loop pair). For each invocation and each outer-loop iteration, "
            "define one outer iteration as one execution of the first outer-loop body line (line 739 for image, "
            "line 760 for audio). Define inner-iteration count as the number of executions of the first inner-loop "
            "body line (line 744 for image, line 765 for audio) that occur within that same outer iteration. "
            "Return JSON with exactly two top-level keys: `loop_headers` and `invocations`. "
            "`loop_headers` is an object with integer keys `image_outer`, `image_inner`, `audio_outer`, "
            "and `audio_inner`. `invocations` is an array sorted by `invocation_index` ascending. "
            "Each element has keys: `invocation_index` (int), `image_inner_iterations_per_outer` (array), "
            "and `audio_inner_iterations_per_outer` (array). Each of those arrays is sorted by `outer_iteration` "
            "ascending and contains objects with keys `outer_iteration` (int, 1-based within that invocation for "
            "that outer loop) and `inner_iterations` (int)."
        ),
        "template_answer": {
            "loop_headers": {
                "image_outer": "int",
                "image_inner": "int",
                "audio_outer": "int",
                "audio_inner": "int",
            },
            "invocations": [
                {
                    "invocation_index": "int",
                    "image_inner_iterations_per_outer": [
                        {"outer_iteration": "int", "inner_iterations": "int"}
                    ],
                    "audio_inner_iterations_per_outer": [
                        {"outer_iteration": "int", "inner_iterations": "int"}
                    ],
                }
            ],
        },
        "oracle_answer": oracle_answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, ensure_ascii=True))


if __name__ == "__main__":
    main()
