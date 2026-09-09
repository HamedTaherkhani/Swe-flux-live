from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/core/downloader/handlers/_base_streaming.py"
TARGET_FUNC = (
    "scrapy.core.downloader.handlers._base_streaming."
    "BaseStreamingDownloadHandler._read_response"
)
INVOCATION = 2

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def statement_line_normalizer(source_path: Path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_read_response"
            and node.lineno == 157
        ),
        None,
    )
    if target is None:
        fail(f"could not locate target function in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt) and node is not target
    ]
    starts = {node.lineno for node in statements}
    source_lines = source_path.read_text(encoding="utf-8").splitlines()

    def normalize(line: int) -> int:
        if line in starts:
            return line
        text = source_lines[line - 1].lstrip()
        if text.startswith(("except ", "else:", "finally:", "case ")):
            return line
        enclosing = [
            node
            for node in statements
            if node.lineno < line <= getattr(node, "end_lineno", node.lineno)
        ]
        if not enclosing:
            return line
        innermost = min(
            enclosing,
            key=lambda node: (
                getattr(node, "end_lineno", node.lineno) - node.lineno,
                -node.lineno,
            ),
        )
        return innermost.lineno

    return normalize


def parse_events(trace_path: Path):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                (
                    match.group("event"),
                    int(match.group("line")),
                    Path(match.group("file")),
                )
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def build_answer(events):
    calls = [index for index, event in enumerate(events) if event[0] == "call"]
    if len(calls) < INVOCATION:
        fail(f"trace has only {len(calls)} target call events; need {INVOCATION}")

    start = calls[INVOCATION - 1]
    end = calls[INVOCATION] if len(calls) > INVOCATION else len(events)
    invocation_events = events[start:end]

    source_path = invocation_events[0][2]
    normalize = statement_line_normalizer(source_path)
    line_numbers = [
        normalize(line) for event, line, _path in invocation_events if event == "line"
    ]
    if not line_numbers:
        fail(f"target invocation {INVOCATION} contains zero line events")

    return {
        "executed_path": [
            {"file": TARGET_FILE, "func": TARGET_FUNC, "line": line}
            for line in line_numbers
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    answer = build_answer(parse_events(Path(args.trace_log)))
    question = (
        "Run the single pytest test "
        "`scrapy_qa/base_streaming_read_response_s1_cfg/files/testcase.py::"
        "StreamingPathTest::test_indirect_download_sequence`. During that test, "
        "consider `BaseStreamingDownloadHandler._read_response` in "
        "`scrapy/core/downloader/handlers/_base_streaming.py`, whose fully qualified "
        "function name is `scrapy.core.downloader.handlers._base_streaming."
        "BaseStreamingDownloadHandler._read_response`. What is the exact ordered "
        "sequence of executed line events in the function's second invocation? "
        "An invocation is one Python tracing `call` event for this function, counted "
        "1-based in chronological order during this test; if Python reports a call "
        "when resuming a suspended coroutine, that call is counted as another "
        "invocation. Include only `line` events from the second invocation, beginning "
        "after its `call` event and ending before the next `call` event for this "
        "function (or at test completion if there is no later call). Exclude `call`, "
        "`return`, and `exception` events. Preserve chronological event order and "
        "preserve all duplicates; do not sort or deduplicate the sequence. Line "
        "numbers are absolute 1-based source line numbers in the named repository "
        "file as it exists for the test. The `def` line, decorator lines, and "
        "docstring lines do not appear because they do not produce included line "
        "events. For a line event reported on a continuation line of a multi-line "
        "statement or expression, report the 1-based line where the innermost "
        "enclosing Python AST statement begins; for example, an event on an argument "
        "line of a multi-line `return call(...)` is reported at the `return` line. "
        "A traced clause header such as an `except` line is retained at its own line "
        "rather than mapped to its enclosing `try`. Return exactly an object with "
        "key `executed_path`; its value is a JSON array of objects in that event "
        "order. Every element must have exactly `file` (string), `func` (string), "
        "and `line` (integer). In every element, `file` is exactly the repository-"
        "relative path named above (forward slashes), and `func` is exactly the fully "
        "qualified name named above. JSON integers are used directly, with no string "
        "conversion and no representation of local values."
    )

    payload = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": question,
        "template_answer": {
            "executed_path": [{"file": "str", "func": "str", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
