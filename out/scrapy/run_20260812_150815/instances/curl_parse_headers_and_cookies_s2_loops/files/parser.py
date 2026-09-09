#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scrapy/utils/curl.py"
TARGET_FUNC = "scrapy.utils.curl._parse_headers_and_cookies"
LOOP_HEADER_LINE = 72

QUESTION = (
    "Run only the pytest test "
    "`scrapy_qa/curl_parse_headers_and_cookies_s2_loops/files/testcase.py::"
    "TestGeneratedCurlCookies::test_generated_headers_and_cookie_options`. "
    "During that test run, consider the first invocation of "
    "`scrapy.utils.curl._parse_headers_and_cookies` in "
    "`scrapy/utils/curl.py`. An invocation means one call of that function, "
    "numbered 1-based in chronological call order. For the `for` loop whose "
    "header is at line 72, what is its total iteration count during that first "
    "invocation, aggregated across every time execution reaches that loop? "
    "An iteration is counted each time the loop body's first statement, at "
    "line 73, begins execution; count these executions chronologically, "
    "starting at 1, without filtering or deduplicating them. Line numbers are "
    "absolute 1-based physical lines in the named repository file as it exists "
    "for this test. For a multi-line statement, its beginning line is the line "
    "on which that statement starts; decorator, `def`, and docstring lines do "
    "not count as loop-body executions. Return exactly one JSON object with "
    "the key `loop_iteration_count` and an integer value; the value is a JSON "
    "number, not a string, and there are no ordering or tie-breaking choices "
    "because the object has one required key."
)

TRACE_RE = re.compile(
    rf"(?P<file>/\S*{re.escape(TARGET_FILE)}):(?P<line>\d+) "
    rf"(?P<func>{re.escape(TARGET_FUNC)}) event=(?P<event>\w+)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def loop_body_first_line(source_path: Path) -> int:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot inspect target source {source_path}: {exc}")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == "_parse_headers_and_cookies"
        ):
            loops = [
                child
                for child in ast.walk(node)
                if isinstance(child, (ast.For, ast.AsyncFor, ast.While))
                and child.lineno == LOOP_HEADER_LINE
            ]
            if len(loops) != 1 or not loops[0].body:
                fail(
                    f"expected exactly one non-empty loop at line "
                    f"{LOOP_HEADER_LINE}"
                )
            return loops[0].body[0].lineno
    fail("target function was not found in target source")


def count_first_invocation(trace_path: Path, body_line: int) -> int:
    try:
        trace_text = trace_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read trace log {trace_path}: {exc}")
    if not trace_text.strip():
        fail(f"trace log is missing or empty: {trace_path}")

    events = []
    for raw_line in trace_text.splitlines():
        match = TRACE_RE.search(raw_line)
        if match:
            events.append((match.group("event"), int(match.group("line"))))
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    active = False
    completed = False
    count = 0
    for event, line_number in events:
        if not active:
            if event == "call":
                active = True
            continue
        if event == "call":
            fail("unexpected recursive target call in first invocation")
        if event == "line" and line_number == body_line:
            count += 1
        if event == "return":
            completed = True
            break

    if not active:
        fail("trace has target events but no target call event")
    if not completed:
        fail("first target invocation has no return event")
    if count == 0:
        fail(f"loop body line {body_line} executed zero times")
    return count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    body_line = loop_body_first_line(source_path)
    answer = count_first_invocation(args.trace_log, body_line)
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": answer},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: unexpected parser failure: {exc}", file=sys.stderr)
        raise
