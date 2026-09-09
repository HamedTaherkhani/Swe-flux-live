#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


TARGET_FUNC = "haystack.components.rankers.transformers_similarity.run"
LOOP_HEADER_LINE = 303
LOOP_BODY_FIRST_LINE = 304

EVENT_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def compute_iteration_count(trace_path: Path) -> int:
    if not trace_path.is_file():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    target_events = 0
    invocation_number = 0
    in_first_invocation = False
    iteration_count = 0

    with trace_path.open(encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            match = EVENT_RE.match(raw_line.rstrip("\n"))
            if match is None or match.group("func") != TARGET_FUNC:
                continue

            target_events += 1
            event = match.group("event")
            line = int(match.group("line"))

            if event == "call":
                invocation_number += 1
                in_first_invocation = invocation_number == 1
                continue

            if in_first_invocation and event == "line" and line == LOOP_BODY_FIRST_LINE:
                iteration_count += 1

            if in_first_invocation and event == "return":
                in_first_invocation = False

    if target_events == 0:
        raise SystemExit(f"ERROR: trace contains zero events for {TARGET_FUNC}")
    if invocation_number == 0:
        raise SystemExit(f"ERROR: trace contains no call event for {TARGET_FUNC}")
    if iteration_count == 0:
        raise SystemExit(
            f"ERROR: loop at line {LOOP_HEADER_LINE} had no observable iterations "
            "in the first target invocation"
        )
    return iteration_count


def main():
    args = parse_args()
    iteration_count = compute_iteration_count(Path(args.trace_log))

    question = (
        "Run only the pytest test "
        "`haystack_qa/transformers_similarity_run_s2_loops/files/testcase.py::"
        "TestTransformersSimilarityRunLoops::test_seeded_batched_ranking`. During the first invocation of "
        "`haystack.components.rankers.transformers_similarity.TransformersSimilarityRanker.run` in "
        "`haystack/components/rankers/transformers_similarity.py`, what is the exact iteration count of the "
        "`for features in inp_dataloader` loop whose header is at line 303? An invocation means one call of "
        "that exact function; invocations are numbered 1-based in chronological order during this test. An "
        "iteration means the Nth execution, counted 1-based, in that invocation's own function frame, of the "
        "loop body's first executable line, the `model_preds = self.model(**features).logits.squeeze(dim=1)` "
        "statement beginning at line 304. Count every such execution in chronological order, without sorting "
        "or deduplication. Ignore all events in called functions, including the data-loader, model, "
        "comprehension, and generator frames. Line numbers are absolute, 1-based source lines in the named "
        "file as it exists in the repository; for a multi-line statement, use the line where the statement "
        "begins. The function's decorator, `def` line, and docstring lines do not count as loop iterations. "
        "Return exactly one JSON object with the key `loop_iteration_count`; its value is the total count as "
        "a JSON integer, not a string. No value serialization, ordering, or tie-breaking rule applies beyond "
        "that integer because the answer contains one scalar."
    )

    oracle = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle, sort_keys=True))


if __name__ == "__main__":
    main()
