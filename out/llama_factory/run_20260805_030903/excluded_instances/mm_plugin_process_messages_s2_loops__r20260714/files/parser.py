#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/src/llamafactory/data/mm_plugin.py"
TARGET_FUNC_SUFFIX = ".process_messages"
TARGET_CALL_LINE = 1363
TARGET_FUNC_START = 1363
TARGET_FUNC_END = 1491
TARGET_LOOP_LINE = 1465
TARGET_LOOP_FIRST_BODY_LINE = 1466

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
    return trace_log.read_text(encoding="utf-8").splitlines()


def collect_iterations(trace_lines: list[str]) -> list[int]:
    invocation_count = 0
    matched_target_events = 0
    active_invocations: list[int] = []
    iterations_per_invocation: dict[int, int] = {}

    for line in trace_lines:
        match = TRACE_RE.match(line)
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
            matched_target_events += 1
            invocation_count += 1
            active_invocations.append(invocation_count)
            iterations_per_invocation.setdefault(invocation_count, 0)
            continue

        if event == "line":
            if lineno < TARGET_FUNC_START or lineno > TARGET_FUNC_END:
                continue
            matched_target_events += 1
            if not active_invocations:
                raise SystemExit(
                    "Malformed trace: line event observed without an active Qwen2OmniPlugin.process_messages call."
                )

            if lineno == TARGET_LOOP_FIRST_BODY_LINE:
                current_invocation = active_invocations[-1]
                iterations_per_invocation[current_invocation] += 1
            continue

        if event in {"return", "exception"}:
            if lineno < TARGET_FUNC_START or lineno > TARGET_FUNC_END:
                continue
            matched_target_events += 1
            if not active_invocations:
                raise SystemExit(
                    "Malformed trace: return/exception event observed without an active "
                    "Qwen2OmniPlugin.process_messages call."
                )
            active_invocations.pop()
            continue

    if matched_target_events == 0:
        raise SystemExit("Trace contains zero events for target function Qwen2OmniPlugin.process_messages.")
    if invocation_count == 0:
        raise SystemExit("Trace did not contain any invocation of Qwen2OmniPlugin.process_messages.")
    if active_invocations:
        raise SystemExit("Malformed trace: unterminated Qwen2OmniPlugin.process_messages invocation.")

    return [iterations_per_invocation[i] for i in range(1, invocation_count + 1)]


def main() -> None:
    args = parse_args()
    trace_lines = read_trace_lines(Path(args.trace_log))
    iterations_per_invocation = collect_iterations(trace_lines)

    if len(iterations_per_invocation) == 0:
        raise SystemExit("No invocations found to report.")

    oracle = {
        "question_kind": "S2_Loops",
        "question": (
            "During execution of pytest test "
            "`llama_factory_qa/mm_plugin_process_messages_s2_loops__r20260714/files/testcase.py::"
            "TestQwen2OmniProcessMessagesLoops::test_audio_video_chunk_loop_iterations`, "
            "consider function `src.llamafactory.data.mm_plugin.Qwen2OmniPlugin.process_messages` in "
            "`src/llamafactory/data/mm_plugin.py`. Focus on the loop whose header is at source line 1465 "
            "(`for j in range(max(len(video_chunk_indices), len(audio_chunk_indices))):`). "
            "Count function invocations in 1-based order by each entry into `process_messages` during this test run. "
            "For each invocation, define one loop iteration as one execution of the first line in that loop body "
            "(source line 1466). Return JSON with exactly two keys: "
            "`loop_line` (int), and `iterations_per_invocation` (array of int). "
            "`iterations_per_invocation[k-1]` must correspond to invocation k; preserve this invocation order exactly."
        ),
        "template_answer": {
            "loop_line": "int",
            "iterations_per_invocation": ["int"],
        },
        "oracle_answer": {
            "loop_line": TARGET_LOOP_LINE,
            "iterations_per_invocation": iterations_per_invocation,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], ensure_ascii=True))


if __name__ == "__main__":
    main()

