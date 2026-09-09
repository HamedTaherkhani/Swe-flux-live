import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/downloadermiddlewares/cookies.py"
TARGET_FUNC = (
    "scrapy.downloadermiddlewares.cookies.CookiesMiddleware._format_cookie"
)
LOOP_HEADER_LINE = 148
LOOP_BODY_FIRST_LINE = 149

QUESTION = """Run only the pytest class node `scrapy_qa/cookies_format_cookie_m2_loops/files/testcase.py::TestCookieFormattingLoops`, meaning all methods in that class whose names begin with `test_`. Aggregate the answer over ALL of those test methods. Each method is identified by its full pytest id of the form `scrapy_qa/cookies_format_cookie_m2_loops/files/testcase.py::TestCookieFormattingLoops::test_method_name`; pytest determines method execution order, and invocations continue in that order across method boundaries. During that complete class run, consider exactly `scrapy.downloadermiddlewares.cookies.CookiesMiddleware._format_cookie` in the repository-relative file `scrapy/downloadermiddlewares/cookies.py`.

For the `for` loop whose header is absolute source line 148 (`for key, value in decoded.items():`), what is the total number of iterations summed over every completed invocation of the target function during the complete class run? An invocation means one `call` of exactly the named target function and is numbered from 1 in chronological execution order, including calls whose loop executes zero times. Count only execution in the target function's own frame: exclude every other function, nested callee, comprehension frame, generator resumption, and any activity before the target call or after its return. Retain all invocation contributions without deduplication.

The loop is identified by its header line, but one iteration means one execution of the loop body's first line, absolute line 149 (`cookie_str += f"; {key.capitalize()}={value}"`), within the same invocation. Therefore, sum the number of times line 149 executes between each target invocation's call and return. The loop-header evaluation and final exhaustion check do not count as iterations. Line numbers are absolute, 1-based line numbers in the named file as it exists in the repository. A line executes when Python executes the statement or expression beginning on that line; for a multi-line statement or expression, execution is attributed to the absolute line where it begins. The function's `def` line, decorator lines, comments, blank lines, and docstring lines are not iterations.

Return a JSON object with exactly one key, `total_iterations`, and no additional keys. Its value is a JSON integer equal to the arithmetic sum just defined. The key spelling is exact. Do not convert the integer to a string, sort or deduplicate contributions, apply `repr()` or `str()`, or substitute JSON `null`; a zero contribution from an invocation contributes integer zero to the sum."""

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
    active_iterations: int | None = None
    invocation_iterations: list[int] = []

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
            if active_iterations is not None:
                fail("target invocations overlap unexpectedly")
            active_iterations = 0
            continue
        if active_iterations is None:
            fail("encountered a target event outside an invocation")
        if event == "line" and line_number == LOOP_BODY_FIRST_LINE:
            active_iterations += 1
        elif event == "exception":
            fail("target invocation raised an exception")
        elif event == "return":
            invocation_iterations.append(active_iterations)
            active_iterations = None

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if active_iterations is not None:
        fail("trace ended during an active target invocation")
    if not invocation_iterations:
        fail("trace contains no completed target invocations")

    total_iterations = sum(invocation_iterations)
    if total_iterations < 15:
        fail(
            f"loop at line {LOOP_HEADER_LINE} executed too few times: "
            f"{total_iterations}"
        )
    return {"total_iterations": total_iterations}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"total_iterations": "int"},
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
