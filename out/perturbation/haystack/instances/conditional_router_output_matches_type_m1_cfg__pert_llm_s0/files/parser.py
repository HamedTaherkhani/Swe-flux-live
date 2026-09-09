#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "haystack/components/routers/conditional_router.py"
TARGET_FUNC = "haystack.components.routers.conditional_router.ConditionalRouter._output_matches_type"
TARGET_CLASS = "ConditionalRouter"
TARGET_METHOD = "_output_matches_type"

EVENT_RE = re.compile(
    r"(?P<file>/\S*haystack/components/routers/conditional_router\.py):(?P<line>\d+) "
    r"(?P<func>haystack\.components\.routers\.conditional_router\._output_matches_type) "
    r"event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest class node
`haystack_qa/conditional_router_output_matches_type_m1_cfg/files/testcase.py::TestConditionalRouterOutputTypes`
in a fresh process. Aggregate over ALL `def test_...` methods selected by that
class node. The methods are identified by their full pytest ids beneath that
class node; their execution order is immaterial because the requested values
are totals.

For
`haystack.components.routers.conditional_router.ConditionalRouter._output_matches_type`
as defined in `haystack/components/routers/conditional_router.py`, report the
total number of Python runtime `line` events at every physical line in the
function body, which is lines 434 through 481 inclusive. Count events from
every invocation reached during the complete class run, including recursive
invocations. An invocation is one runtime `call` event for that exact function;
if invocations were numbered, they would be 1-based in chronological
call-event order, but the requested counts sum across all of them.

Only events in that exact function's own frames count. Exclude its `call`,
`return`, and `exception` events. Also exclude events in callers, callees,
generator-expression or comprehension frames, and other nested frames, even
when their qualified names contain the target function's name. Preserve
duplicate line events by adding one to the corresponding line's count for
every occurrence; do not deduplicate events.

Line numbers are absolute, 1-based source line numbers in the named repository
file as it exists for this run. The `def` line 433 is excluded, and there are
no decorator lines for this method. Every physical body line in the inclusive
range is in scope, including docstring, blank, comment, and continuation lines.
Any in-scope line for which Python emits no line event must still be reported
with count 0. For a multi-line statement or expression, attribute an event to
the exact physical line exposed as `frame.f_lineno` for that event by the
Python interpreter running pytest. Do not normalize such an event to the
statement's first line or spread it over all visual continuation lines; a
continuation line has a nonzero count only if the interpreter reports an event
at that continuation line.

Return exactly one JSON object with the key `line_execution_counts`. Its value
must be a list containing one object for every in-scope physical line. Each
object has exactly two integer-valued keys, written in the order `count`,
`line`. Sort the list by `line` in strictly ascending order; there is exactly
one object per line, so no tie-breaker is needed. Counts are ordinary JSON
integers, including zero. Do not add prose or any other keys."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def target_body_range(source_path: Path) -> range:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")

    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == TARGET_METHOD:
                    if child.end_lineno is None:
                        fail(f"AST has no end line for {TARGET_FUNC}")
                    return range(child.lineno + 1, child.end_lineno + 1)
    fail(f"could not locate {TARGET_FUNC} in {source_path}")


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    raw_trace = trace_path.read_text(encoding="utf-8")
    if not raw_trace.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in raw_trace.splitlines():
        match = EVENT_RE.search(raw_line)
        if match:
            target_events.append((match.group("event"), int(match.group("line"))))
    if not target_events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    body_lines = target_body_range(Path(TARGET_FILE))
    body_line_set = set(body_lines)
    line_counts = Counter(
        line for event, line in target_events if event == "line" and line in body_line_set
    )
    if not line_counts:
        fail(f"trace contains zero in-scope line events for {TARGET_FUNC}")

    line_execution_counts = [
        {"count": line_counts[line], "line": line} for line in body_lines
    ]
    document = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": {"line_execution_counts": line_execution_counts},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote oracle with {len(line_execution_counts)} per-line counts "
        f"from {sum(line_counts.values())} line events to {output_path}"
    )


if __name__ == "__main__":
    main()
