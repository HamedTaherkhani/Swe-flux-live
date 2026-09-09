import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/core/http2/stream.py"
TARGET_FUNC = "scrapy.core.http2.stream.Stream._get_request_headers"
LOOP_HEADER_LINE = 255
LOOP_BODY_FIRST_LINE = 256

QUESTION = """Run only the pytest class node `scrapy_qa/stream_get_request_headers_m2_loops/files/testcase.py::TestStreamRequestHeaderLoops`, which means all methods whose names begin with `test_` in that class. Aggregate the answer over every such test method; each method is identified by its full pytest id of the form `scrapy_qa/stream_get_request_headers_m2_loops/files/testcase.py::TestStreamRequestHeaderLoops::test_method_name`, and pytest determines their execution order. During that complete run, consider `scrapy.core.http2.stream.Stream._get_request_headers` in the repository-relative file `scrapy/core/http2/stream.py`.

For the inner `for` loop whose header is absolute source line 255, what are the maximum and minimum numbers of iterations among all invocations of the target function? An invocation means one `call` of exactly `scrapy.core.http2.stream.Stream._get_request_headers`; invocations are numbered from 1 in chronological execution order across the complete class run. Include every completed invocation caused by every named test method, retain duplicate per-invocation counts when taking the extrema, and do not include calls to any other function, nested callee, comprehension frame, or generator resumption.

The loop is identified by its header line, but an iteration is counted as one execution of the loop body's first line, absolute line 256 (`value = str(value_bytes, "utf-8")`), within that same target invocation. Thus the iteration count for an invocation is the number of times line 256 executes between that invocation's call and return; the loop-header evaluation itself and its final exhaustion check do not add iterations. Line numbers are absolute, 1-based line numbers in the named file as it exists in the repository. A line executes when Python executes the statement or expression beginning on that line; for a multi-line statement or expression, execution is attributed to the absolute line where it begins. The function's `def` line, decorator lines, comments, blank lines, and unexecuted docstring lines are not loop iterations.

Return a JSON object with exactly the keys `max_iterations` and `min_iterations`, with no additional keys. Both values are JSON integers: `max_iterations` is the numerically greatest retained per-invocation count and `min_iterations` is the numerically least retained per-invocation count. Key names are exactly as shown; no sorting, string conversion, deduplication, null substitution, or other normalization is applied to the integer values."""

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, int]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    active_count: int | None = None
    invocation_counts: list[int] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            if active_count is not None:
                fail("target invocations overlap unexpectedly")
            active_count = 0
            continue
        if active_count is None:
            fail("encountered a target event outside an invocation")
        if event == "line" and line_number == LOOP_BODY_FIRST_LINE:
            active_count += 1
        elif event == "return":
            invocation_counts.append(active_count)
            active_count = None
        elif event == "exception":
            fail("target invocation raised an exception")

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active_count is not None:
        fail("trace ended during an active target invocation")
    if not invocation_counts:
        fail("trace contains no completed target invocations")
    if min(invocation_counts) <= 0:
        fail(
            f"loop at line {LOOP_HEADER_LINE} did not iterate in every invocation"
        )
    if len(set(invocation_counts)) < 6:
        fail("fewer than six distinct per-invocation loop counts were observed")

    return {
        "max_iterations": max(invocation_counts),
        "min_iterations": min(invocation_counts),
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {
            "max_iterations": "int",
            "min_iterations": "int",
        },
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
