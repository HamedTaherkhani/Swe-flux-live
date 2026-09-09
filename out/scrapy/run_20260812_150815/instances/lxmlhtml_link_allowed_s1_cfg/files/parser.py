from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/linkextractors/lxmlhtml.py"
TARGET_FUNC = "scrapy.linkextractors.lxmlhtml.LxmlLinkExtractor._link_allowed"
TARGET_NAME = "_link_allowed"
TARGET_DEF_LINE = 361
INVOCATION = 29

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def statement_line_normalizer(source_path: Path):
    try:
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
    except (OSError, SyntaxError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_NAME
            and node.lineno == TARGET_DEF_LINE
        ),
        None,
    )
    if target is None:
        fail(f"could not locate target function at {source_path}:{TARGET_DEF_LINE}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt) and node is not target
    ]
    statement_starts = {node.lineno for node in statements}

    def normalize(line: int) -> int:
        if line in statement_starts:
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
            source_path = Path(match.group("file"))
            if not source_path.as_posix().endswith(f"/{TARGET_FILE}"):
                fail(f"target event came from unexpected file: {source_path}")
            events.append(
                {
                    "event": match.group("event"),
                    "line": int(match.group("line")),
                    "path": source_path,
                }
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def build_answer(events):
    call_indices = [
        index for index, event in enumerate(events) if event["event"] == "call"
    ]
    if len(call_indices) < INVOCATION:
        fail(
            f"trace has only {len(call_indices)} target call events; "
            f"need invocation {INVOCATION}"
        )

    start = call_indices[INVOCATION - 1]
    end = (
        call_indices[INVOCATION]
        if len(call_indices) > INVOCATION
        else len(events)
    )
    invocation_events = events[start:end]
    source_paths = {event["path"].resolve() for event in invocation_events}
    if len(source_paths) != 1:
        fail(
            f"selected invocation refers to {len(source_paths)} source paths; "
            "expected one"
        )

    normalize = statement_line_normalizer(next(iter(source_paths)))
    line_numbers = [
        normalize(event["line"])
        for event in invocation_events
        if event["event"] == "line"
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
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = build_answer(parse_events(Path(args.trace_log)))
    question = (
        "Run the single pytest test "
        "`scrapy_qa/lxmlhtml_link_allowed_s1_cfg/files/testcase.py::"
        "LinkAllowedPathTest::test_generated_filter_matrix`. During that test, "
        "consider `LxmlLinkExtractor._link_allowed` in "
        "`scrapy/linkextractors/lxmlhtml.py`, whose fully qualified function name "
        "is `scrapy.linkextractors.lxmlhtml.LxmlLinkExtractor._link_allowed`. "
        "What is the exact ordered sequence of executed line events inside the "
        "function's 29th invocation? An invocation is one Python tracing `call` "
        "event whose frame is exactly that fully qualified function, counted "
        "1-based in chronological order during this test. Include only Python "
        "tracing `line` events from that exact frame after the 29th `call` event "
        "and before the next `call` event for the function (or test completion if "
        "there is no later call); events in callers and callees do not count. "
        "Exclude `call`, `return`, and `exception` events. Preserve chronological "
        "event order and preserve every duplicate; do not sort or deduplicate. "
        "Line numbers are absolute 1-based source line numbers in the named "
        "repository file as it exists for the test. The `def` line, decorator "
        "lines, and docstring lines do not appear; this function has no docstring. "
        "This function contains multi-line conditions and calls. If Python reports "
        "a line event on a continuation line of a multi-line statement or "
        "expression, report instead the line where the innermost enclosing Python "
        "AST statement begins, while preserving that event as a separate sequence "
        "element. For example, an event on an argument continuation line of a "
        "multi-line `return make_value(...)` is reported at the `return` line; if "
        "both lines generated events, the normalized line number appears twice. "
        "Return exactly one JSON object with key `executed_path`. Its value is a "
        "JSON array in that event order, and every element has exactly three keys: "
        "`file` (string), `func` (string), and `line` (integer). In every element, "
        "`file` is exactly the repository-relative path named above using forward "
        "slashes, and `func` is exactly the fully qualified name named above. "
        "Use JSON integers directly, not strings; no local values and therefore no "
        "`repr`, `str`, empty-value, or null convention are part of the answer."
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
