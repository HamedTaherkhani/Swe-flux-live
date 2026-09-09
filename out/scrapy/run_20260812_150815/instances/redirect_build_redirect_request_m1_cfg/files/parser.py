#!/usr/bin/env python3
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/downloadermiddlewares/redirect.py"
TARGET_FUNC = (
    "scrapy.downloadermiddlewares.redirect."
    "BaseRedirectMiddleware._build_redirect_request"
)

QUESTION = """Run the pytest class selection `scrapy_qa/redirect_build_redirect_request_m1_cfg/files/testcase.py::TestRedirectRequestControlFlow`. Aggregate over ALL 12 test methods in that class: `test_authorization_default_port_equivalence`, `test_authorization_port_changes`, `test_both_sensitive_headers_cross_origin`, `test_cookie_http_to_https_same_host`, `test_cookie_https_to_http_is_removed`, `test_cookie_same_origin_relative_locations`, `test_cookie_subdomain_changes`, `test_no_sensitive_headers_mixed_hosts`, `test_post_redirects_rebuild_as_get`, `test_proxy_metadata_cross_scheme`, `test_proxy_metadata_same_scheme`, and `test_status_303_non_get_rebuilds`. Equivalently, these are the 12 pytest IDs formed by appending `::<method name>` to that class selection. What are the total runtime line-event execution counts for every physical source line in the body of `scrapy.downloadermiddlewares.redirect.BaseRedirectMiddleware._build_redirect_request` in `scrapy/downloadermiddlewares/redirect.py`?

The body scope is the inclusive physical line range from the first body statement through the function's final statement, as determined from the repository version's Python AST. It excludes the decorator, `def` line, and signature continuation lines. Include every integer line number in that inclusive body range. Blank lines, comment-only lines, and purely syntactic continuation lines remain in the output with count 0. For a multi-line statement or expression, credit each runtime `line` event to its absolute, 1-based `frame.f_lineno`: normally this is the physical line where the statement or executable subexpression begins. A continuation line that begins no executable subexpression therefore has count 0; do not normalize an event on an executable continuation line back to the statement's first line.

Count only Python runtime events whose event type is exactly `line` and whose frame is exactly that target function in the named file. Ignore `call`, `return`, and `exception` events, and ignore events in callers, callees (including `handle_referer`), and all other frames. An invocation means one runtime `call` event for this exact function; counts are totals summed over every invocation made by all 12 test methods, with repeated events retained rather than deduplicated. Test execution order and invocation chronology do not affect these totals.

Return exactly one JSON object with key `line_execution_counts`. Its value must be a JSON array containing one object for every line in the inclusive body range. Each object has exactly `count` (a JSON integer) and `line` (a JSON integer). Sort objects by `line` numerically ascending; line numbers are unique, so there is no tie-breaker. Emit counts and line numbers directly as JSON integers, with no `repr()` or `str()` conversion."""

TRACE_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    + re.escape(TARGET_FUNC)
    + r"\s+event=(?P<event>call|line|return|exception)\b"
)


def target_body_range(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "BaseRedirectMiddleware":
            target = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "_build_redirect_request"
                ),
                None,
            )
            break
    if target is None or not target.body:
        raise RuntimeError(f"target function not found in {source_path}")
    return target.body[0].lineno, target.body[-1].end_lineno


def parse_trace(trace_path, source_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    first_line, last_line = target_body_range(source_path)
    counts = Counter()
    target_event_count = 0
    call_count = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.search(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        target_event_count += 1
        event = match.group("event")
        if event == "call":
            call_count += 1
        elif event == "line":
            line = int(match.group("line"))
            if not first_line <= line <= last_line:
                raise RuntimeError(
                    f"target line event {line} is outside body range "
                    f"{first_line}-{last_line}"
                )
            counts[line] += 1

    if target_event_count == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if call_count == 0:
        raise RuntimeError(f"trace contains no call events for {TARGET_FUNC}")
    if not counts:
        raise RuntimeError(f"trace contains no line events for {TARGET_FUNC}")

    return {
        "line_execution_counts": [
            {"count": counts[line], "line": line}
            for line in range(first_line, last_line + 1)
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise RuntimeError(f"target source is missing: {source_path}")

    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": parse_trace(args.trace_log, source_path),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
