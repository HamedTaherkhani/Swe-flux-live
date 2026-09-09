from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/types.py"
REPO_FILE = Path("src/click/types.py")
TARGET_FUNC = "click.types.convert_type"
TARGET_DEF_LINE = 1341

QUESTION = """Run every pytest test method in the class `TestIndirectChoiceMetavars` in `click_qa/types_convert_type_m1_cfg/files/testcase.py`, equivalently every collected pytest id below `click_qa/types_convert_type_m1_cfg/files/testcase.py::TestIndirectChoiceMetavars`. Pytest identifies and runs those methods by their full pytest ids in its normal ascending method-name order. Aggregate the requested counts over ALL test methods in the class. During that complete class run, consider every invocation of the target function `click.types.convert_type` defined at `src/click/types.py:1341`, including invocations reached recursively or through constructors beneath `click.types.Choice.get_metavar`.

Report exactly one row for every absolute, 1-based physical source line in the target function's body, which is the inclusive range 1344 through 1382 in `src/click/types.py`. This scope includes docstring lines, blank lines, comment-only lines, and continuation lines. Such a line remains in the answer with `count` 0 when it produces no qualifying event; it is not removed.

A line execution is one standard Python runtime `line` event emitted while the active frame is exactly `click.types.convert_type`. Only `line` events count: the function's `call`, `return`, and `exception` events do not. Events in `_guess_type`, `Tuple.__init__`, `Choice.get_metavar`, comprehensions, or any other frame do not count, although a fresh or recursive call that creates another `convert_type` frame is counted normally. For a multi-line statement or expression, assign an event to the absolute 1-based physical line reported as that event's `f_lineno`: this is the line where the currently executable statement or subexpression begins, rather than a closing delimiter or a merely visual continuation. For example, in a hypothetical multi-line call whose argument expression begins on its second physical line, an event for evaluating that argument belongs to the second line. Count every repeated event without deduplication.

An invocation means one Python `call` of `click.types.convert_type` during the complete class run. Invocations would be numbered from 1 in chronological call order if they needed to be distinguished, but invocation numbers are not included in the answer. Each row's `count` is the total number of qualifying line events at that line, summed across every invocation in every test method. The implementation `def` line 1341 and its signature continuation lines 1342-1343 are outside the body range and must not appear. The overload declarations and their decorator lines above the implementation are also outside the range and do not count.

Return exactly `{"line_execution_counts": [{"count": "int", "line": "int"}]}`. `line_execution_counts` is a JSON array of 39 objects, one for each line in the inclusive body range and no others. In each object, `line` and `count` are JSON integers, not strings or Python `repr()` values. Sort rows by `line` ascending. Emit each source line exactly once; `count` carries all multiplicity, so there are no duplicate rows and no secondary tie-breaker is needed. Zero is represented by the JSON integer `0`, never by JSON null, an empty string, or an omitted object."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def target_body_range(source_path: Path) -> range:
    if not source_path.exists():
        fail(f"target source does not exist: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    candidates = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "convert_type"
        and node.lineno == TARGET_DEF_LINE
    ]
    if len(candidates) != 1:
        fail(
            f"expected one convert_type implementation at line {TARGET_DEF_LINE}, "
            f"found {len(candidates)}"
        )

    function = candidates[0]
    if not function.body or function.end_lineno is None:
        fail("target function has no statically identifiable body range")
    first_line = min(statement.lineno for statement in function.body)
    last_line = function.end_lineno
    if (first_line, last_line) != (1344, 1382):
        fail(
            "target function body moved: expected lines 1344-1382, "
            f"found {first_line}-{last_line}"
        )
    return range(first_line, last_line + 1)


def parse_trace(trace_path: Path, source_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    body_lines = target_body_range(source_path)
    body_line_set = set(body_lines)
    event_pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    target_events = 0
    target_calls = 0
    counts: Counter[int] = Counter()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue

        filename = match.group("file").replace("\\", "/")
        function = match.group("func")
        if not filename.endswith(TARGET_FILE_SUFFIX) or function != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            target_calls += 1
        elif event == "line":
            line = int(match.group("line"))
            if line in body_line_set:
                counts[line] += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if not counts:
        fail(f"trace contains zero body line events for {TARGET_FUNC}")

    return {
        "line_execution_counts": [
            {"count": counts[line], "line": line} for line in body_lines
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": parse_trace(arguments.trace_log, REPO_FILE),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote oracle to {arguments.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
