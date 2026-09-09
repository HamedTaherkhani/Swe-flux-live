import argparse
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/downloadermiddlewares/redirect.py"
TARGET_FUNC = (
    "scrapy.downloadermiddlewares.redirect.RedirectMiddleware.process_response"
)
INVOCATION_NUMBER = 21

QUESTION = """Run only the pytest test `scrapy_qa/redirect_process_response_s1_cfg/files/testcase.py::RedirectProcessResponsePathTest::test_generated_redirect_matrix`. During that sole test method, consider the 21st invocation of `scrapy.downloadermiddlewares.redirect.RedirectMiddleware.process_response` in the repository-relative file `scrapy/downloadermiddlewares/redirect.py`. What is the exact ordered sequence of executed Python line events within that invocation?

An invocation is one `call` event for exactly that target function, and invocations are counted 1-based in chronological order over the complete named test run. Count only events from the target function's own frame; events in decorators, callers, and callees (including `_build_redirect_request`, `_redirect_request_using_get`, and `_redirect`) do not count. Begin after the selected invocation's `call` event and stop before its matching `return` event. Include every `line` event in emitted chronological order, including repeated line numbers; exclude `call`, `return`, and `exception` events. Do not sort or deduplicate the sequence.

Line numbers are absolute, 1-based line numbers in the named file as it exists in the repository. Each line event uses the executing target frame's `f_lineno`: for a multi-line statement, condition, or call, report the line where the particular executed statement or expression begins, rather than a later closing or continuation-only line. Multi-line conditions and calls in this function can therefore produce events on the beginning lines of their executed constituent expressions, and control flow can produce the same beginning line more than once. The function's `def` line does not appear because its `call` event is excluded; decorator lines do not appear because they are outside the target frame, and there is no executed docstring line.

Return a JSON object with exactly one key, `executed_path`, whose value is a JSON list. Each list element must be an object with exactly the keys `file`, `func`, and `line`: `file` is the string `scrapy/downloadermiddlewares/redirect.py`, `func` is the fully dotted `module.Class.method` string `scrapy.downloadermiddlewares.redirect.RedirectMiddleware.process_response` (for example, an unrelated method could be formatted as `package.module.Widget.run`), and `line` is the integer line number defined above. Preserve chronological event order and all duplicates; there is no secondary ordering or tie-breaker because no sorting is performed. Every element must include all three fields, even though `file` and `func` are identical throughout."""

EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation_count = 0
    collecting = False
    completed = False
    executed_path: list[dict[str, object]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation_count += 1
            if collecting:
                fail("encountered a nested target call before the selected return")
            if invocation_count == INVOCATION_NUMBER:
                collecting = True
            continue

        if not collecting:
            continue
        if event == "line":
            executed_path.append(
                {
                    "file": TARGET_FILE,
                    "func": TARGET_FUNC,
                    "line": int(match.group("line")),
                }
            )
        elif event == "return":
            collecting = False
            completed = True
            break

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if invocation_count < INVOCATION_NUMBER:
        fail(
            f"trace contains only {invocation_count} target invocations; "
            f"need {INVOCATION_NUMBER}"
        )
    if not completed:
        fail("selected invocation has no matching return event")
    if not executed_path:
        fail("selected invocation contains zero line events")

    return {"executed_path": executed_path}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
