from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "kedro/io/data_catalog.py"
TARGET_FUNC = "kedro.io.data_catalog.get"
EVENT_RE = re.compile(
    r"(?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`kedro_qa/data_catalog_get_m1_cfg/files/testcase.py::TestCatalogIndirectControlFlow::test_generated_catalog_accesses`
against this repository. Across the whole test run, what is the exact line
coverage of `kedro.io.data_catalog.DataCatalog.get` in
`kedro/io/data_catalog.py`?

An invocation is one Python `call` event for the frame whose fully qualified
dotted name is exactly `kedro.io.data_catalog.DataCatalog.get`; invocations
are counted 1-based in chronological order. Consider every such invocation
caused by the named test. An executed line is a Python runtime `line` event
from that exact function frame. Exclude `call`, `return`, and `exception`
events, and exclude all events from callers, callees, comprehensions,
generators, and other nested frames.

Report one object with exactly the key `covered_lines`. Its value is a JSON
array of JSON integers containing the union of executed lines across all
invocations. Remove duplicates globally and sort the integers in strictly
ascending numeric order. The exact answer shape is
`{"covered_lines": ["int"]}`; `"int"` is a type placeholder, not an answer
value. There are no string-formatted values, `repr` conversions, null
sentinels, or omitted entries in this answer.

Line numbers are absolute, 1-based source line numbers in the named file as it
exists in this repository. Normalize each runtime line event to the `lineno`
of its smallest enclosing executable Python `ast.stmt` node. Therefore, for
a multi-line condition, call, assignment, or expression, use the line where
that enclosing statement begins (for example, an event on a continuation line
of a statement beginning on line 8 is reported as 8). The function's `def`
line, decorator lines, and docstring lines do not count because they are not
runtime `line` events from an executable statement in the function body."""


def _statement_line_map(source_path: Path) -> dict[int, int]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "get"
            and node.lineno == 555
        ),
        None,
    )
    if target is None:
        raise RuntimeError(f"target function not found in {source_path}")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and hasattr(node, "end_lineno")
    ]
    line_map: dict[int, int] = {}
    for line in range(target.lineno, (target.end_lineno or target.lineno) + 1):
        enclosing = [
            node
            for node in statements
            if node.lineno <= line <= (node.end_lineno or node.lineno)
        ]
        if enclosing:
            smallest = min(
                enclosing,
                key=lambda node: (
                    (node.end_lineno or node.lineno) - node.lineno,
                    -node.lineno,
                ),
            )
            line_map[line] = smallest.lineno
    return line_map


def _read_target_invocations(trace_path: Path) -> list[list[int]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    invocations: list[list[int]] = []
    current: list[int] | None = None
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if (
            not match
            or match.group("func") != TARGET_FUNC
            or not match.group("file").replace("\\", "/").endswith(
                f"/{TARGET_FILE}"
            )
        ):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            if current is not None:
                raise RuntimeError("nested target invocation encountered")
            current = []
            invocations.append(current)
        elif event == "line":
            if current is None:
                raise RuntimeError("target line event appeared outside an invocation")
            current.append(int(match.group("line")))
        elif event == "return":
            current = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if current is not None:
        raise RuntimeError("trace ended before target invocation returned")
    if len(invocations) < 3:
        raise RuntimeError(
            f"trace contains only {len(invocations)} target invocations; need at least 3"
        )
    if any(not invocation for invocation in invocations):
        raise RuntimeError("at least one target invocation has zero line events")
    return invocations


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    line_map = _statement_line_map(Path.cwd() / TARGET_FILE)
    invocations = _read_target_invocations(args.trace_log)
    normalized_paths = [
        tuple(line_map.get(line, line) for line in invocation)
        for invocation in invocations
    ]
    if len(set(normalized_paths)) < 3:
        raise RuntimeError("target invocations exercised fewer than 3 distinct paths")

    covered_lines = sorted(
        {line for invocation in normalized_paths for line in invocation}
    )
    if not covered_lines:
        raise RuntimeError("computed covered_lines is empty")

    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": {"covered_lines": covered_lines},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
