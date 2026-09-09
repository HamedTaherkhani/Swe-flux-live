from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/utils/iterators.py"
TARGET_FUNC = "scrapy.utils.iterators.xmliter_lxml"
TARGET_DEF_LINE = 21
LOOP_HEADER_LINE = 40

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def loop_body_first_line(source_path: Path) -> int:
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
            if isinstance(node, ast.FunctionDef)
            and node.name == "xmliter_lxml"
            and node.lineno == TARGET_DEF_LINE
        ),
        None,
    )
    if target is None:
        fail(f"could not locate {TARGET_FUNC} at line {TARGET_DEF_LINE}")

    loops = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.For) and node.lineno == LOOP_HEADER_LINE
    ]
    if len(loops) != 1 or not loops[0].body:
        fail(f"could not uniquely locate loop at line {LOOP_HEADER_LINE}")
    return loops[0].body[0].lineno


def parse_target_events(trace_path: Path):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                {
                    "event": match.group("event"),
                    "line": int(match.group("line")),
                    "file": Path(match.group("file")),
                }
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def build_answer(events) -> dict[str, int]:
    source_paths = {event["file"] for event in events}
    if len(source_paths) != 1:
        fail(f"target events reference {len(source_paths)} source paths, expected one")
    source_path = next(iter(source_paths))
    if source_path.as_posix().endswith(TARGET_FILE) is False:
        fail(f"target events came from unexpected source file: {source_path}")

    body_line = loop_body_first_line(source_path)
    count = sum(
        event["event"] == "line" and event["line"] == body_line for event in events
    )
    if count == 0:
        fail(
            f"loop at line {LOOP_HEADER_LINE} has zero observed executions "
            f"of its first body line {body_line}"
        )
    return {"loop_iteration_count": count}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = build_answer(parse_target_events(Path(args.trace_log)))
    question = (
        "Run the single pytest test "
        "`scrapy_qa/iterators_xmliter_lxml_s2_loops/files/testcase.py::"
        "XmlIterLoopTest::test_generated_namespaced_catalog`. For the first and "
        "only source-level invocation of `scrapy.utils.iterators.xmliter_lxml` "
        "in `scrapy/utils/iterators.py`, what is the exact iteration count of "
        "the `for event, data in iterable` loop whose header is at absolute "
        "1-based source line 40? An invocation is one evaluation of the "
        "`xmliter_lxml(...)` call expression during the test, counted 1-based "
        "in chronological order; the complete consumption of the generator "
        "created by that expression belongs to that same invocation, and "
        "generator suspension and resumption do not create additional "
        "invocations. Iteration counting is 1-based: iteration N is the Nth "
        "execution of the loop body's first statement, the `if` statement "
        "beginning at absolute 1-based line 41. Count every such execution "
        "during complete generator consumption, including iterations that "
        "later execute `continue` and iterations that reach `yield`; do not "
        "sort, deduplicate, or otherwise group iterations. Line numbers refer "
        "to the named repository file as it exists for this test; the loop "
        "header itself, the function `def` line, decorator lines, and docstring "
        "lines are not counted. Return exactly one JSON object with the sole "
        "key `loop_iteration_count`; its value is the count as a JSON integer, "
        "not a string and not a `repr()` value. No ordering or tie-breaking "
        "rule applies because the answer contains one scalar count."
    )
    payload = {
        "question_kind": "S2_Loops",
        "question": question,
        "template_answer": {"loop_iteration_count": "int"},
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
