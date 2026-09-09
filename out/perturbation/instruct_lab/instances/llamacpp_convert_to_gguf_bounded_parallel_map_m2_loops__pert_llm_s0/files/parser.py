#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/instructlab/llamacpp/llamacpp_convert_to_gguf.py"
TARGET_FUNC = "instructlab.llamacpp.llamacpp_convert_to_gguf.bounded_parallel_map"
LOOP_HEADER_LINE = 1087
LOOP_BODY_FIRST_LINE = 1088
EVENT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>.+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def count_iterations(trace_path: Path) -> int:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    iterations = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        file_name = match.group("file").replace("\\", "/")
        if not file_name.endswith("/" + TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            target_calls += 1
        if event == "line" and int(match.group("line")) == LOOP_BODY_FIRST_LINE:
            iterations += 1

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains no call event for target function {TARGET_FUNC}")
    if iterations == 0:
        fail(
            "trace contains no iterations of the inner while loop at "
            f"line {LOOP_HEADER_LINE}"
        )
    return iterations


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = {"total_iterations": count_iterations(Path(args.trace_log))}
    question = (
        "Run the pytest test "
        "`instruct_lab_qa/llamacpp_convert_to_gguf_bounded_parallel_map_m2_loops/"
        "files/testcase.py::TestBoundedConversionLoops::"
        "test_generated_conversion_workloads` against this repository. In the "
        "target generator function "
        "`instructlab.llamacpp.llamacpp_convert_to_gguf.bounded_parallel_map` in "
        "`src/instructlab/llamacpp/llamacpp_convert_to_gguf.py`, what is the total "
        "number of iterations of the inner `while` loop whose header begins on "
        "line 1087, summed over every invocation made during the complete named "
        "test? Line numbers are absolute, 1-based source line numbers in that "
        "repo-relative file as it exists in the repository. The loop is identified "
        "by the `while not done and len(futures) < concurrency:` header on line "
        "1087. One iteration means one execution, in the target function's own "
        "frame, of the loop body's first executable line: the `try:` statement on "
        "line 1088. Thus each repeated execution of line 1088 counts separately, "
        "including an iteration whose attempt later raises `StopIteration`; "
        "evaluations of the line-1087 condition that do not enter the body do not "
        "count. Do not count executions in callees, worker threads, other functions, "
        "or other source lines. For a multi-line statement, its execution is "
        "assigned to the absolute line on which that statement begins; neither the "
        "function's `def` line, decorators, nor docstring lines count unless they "
        "are the stated body-first line (none is). An invocation is one call by a "
        "caller that creates a distinct generator object for this function; number "
        "invocations 1-based by the chronological order in which those generator "
        "objects first enter the function. Suspending and resuming the same generator "
        "does not create another invocation, but every qualifying line-1088 "
        "execution after a resumption still counts. Include all such invocations "
        "during the named test and sum their qualifying iterations. Preserve "
        "duplicates: perform no deduplication or sorting, because the requested "
        "result is one scalar sum and invocation order does not change it. Return "
        "exactly one JSON object with the single key `total_iterations` and a JSON "
        "integer value. Emit the count as an unquoted base-10 integer, never as a "
        "string, floating-point value, empty value, or JSON null."
    )
    payload = {
        "question_kind": "M2_Loops",
        "question": question,
        "template_answer": {"total_iterations": "int"},
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
