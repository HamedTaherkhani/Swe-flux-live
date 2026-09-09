import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/flask/sansio/app.py"
TARGET_NAME = "flask.sansio.app.App.inject_url_defaults"
LOOP_HEADER_LINE = 976
LOOP_BODY_FIRST_LINE = 977

QUESTION = """Run the complete pytest test `flask_qa/app_inject_url_defaults_m2_loops/files/testcase.py::TestInjectUrlDefaultsLoopDynamics::test_generated_nested_blueprint_defaults`. Consider only invocations of `flask.sansio.app.App.inject_url_defaults` defined in the repository-relative file `src/flask/sansio/app.py`. For the outer `for name in names` loop whose header begins on absolute line 976, what are the maximum and minimum numbers of iterations performed by any one invocation during the test?

An invocation is one Python call of this exact target function during the test, numbered starting at 1 in chronological call order. An iteration of the line-976 loop is one execution, in that invocation's frame, of the loop body's first line, absolute line 977 (the `if name in self.url_default_functions:` statement); for example, three executions of line 977 in one invocation count as 3 iterations. Count each execution, including repeated executions with equal local values, and do not count line events from callbacks or any other function. Compute one iteration count for every invocation, including a zero count if an invocation never executes line 977, then take the extrema over those counts without sorting or deduplicating them.

Line numbers are absolute, 1-based line numbers in `src/flask/sansio/app.py` as it exists in the repository. A line is identified by where the relevant statement begins in the source; the function's `def` line, docstring lines, the loop-header line itself, and return events do not count as loop iterations.

Return a JSON object with exactly the keys `max_iterations` and `min_iterations`, in that order. Each value is a JSON integer (not a string): `max_iterations` is the greatest per-invocation count and `min_iterations` is the least. Do not emit any other keys, omit either key, or use JSON `null`."""


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def parse_target_event(raw_line):
    if f"{TARGET_FILE}:" not in raw_line or f" {TARGET_NAME} event=" not in raw_line:
        return None

    match = re.search(
        rf"{re.escape(TARGET_FILE)}:(\d+) "
        rf"{re.escape(TARGET_NAME)} event=(call|line|return|exception)\b",
        raw_line,
    )
    if match is None:
        fail(f"malformed target event line: {raw_line.rstrip()}")
    return int(match.group(1)), match.group(2)


def harvest(trace_path):
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    active_iterations = None
    invocation_counts = []

    with trace_path.open("r", encoding="utf-8") as trace_file:
        for raw_line in trace_file:
            event = parse_target_event(raw_line)
            if event is None:
                continue

            target_events += 1
            line_number, event_name = event

            if event_name == "call":
                if active_iterations is not None:
                    fail("encountered a nested target call before the prior return")
                active_iterations = 0
            elif active_iterations is None:
                fail(f"encountered target {event_name} event before a call event")
            elif event_name == "line" and line_number == LOOP_BODY_FIRST_LINE:
                active_iterations += 1
            elif event_name == "exception":
                fail("target raised an exception during an invocation")
            elif event_name == "return":
                invocation_counts.append(active_iterations)
                active_iterations = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_NAME}")
    if active_iterations is not None:
        fail("trace ended before the active target invocation returned")
    if not invocation_counts:
        fail(f"trace contains no completed invocations of {TARGET_NAME}")

    return {
        "max_iterations": max(invocation_counts),
        "min_iterations": min(invocation_counts),
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": harvest(args.trace_log),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output_file:
        json.dump(oracle, output_file, indent=2, sort_keys=True)
        output_file.write("\n")

    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
