from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/utils/sitemap.py"
TARGET_FUNC = "scrapy.utils.sitemap.Sitemap._process_sitemap_element"
LOOP_HEADER_LINE = 87

QUESTION = (
    "Run the pytest test "
    "`scrapy_qa/sitemap_process_sitemap_element_s2_loops/files/testcase.py::"
    "SitemapElementLoopTest::test_programmatic_siblings_and_children`. During that "
    "run, consider invocation 1 of `scrapy.utils.sitemap.Sitemap."
    "_process_sitemap_element` in `scrapy/utils/sitemap.py`. An invocation is one "
    "call of that exact function, numbered 1-based in chronological call order. "
    "For the `while` loop whose header is at line 87, how many iterations execute "
    "in invocation 1? Line numbers are absolute, 1-based source line numbers in "
    "the named repository file. Define iteration N (1-based) as the Nth execution "
    "in that invocation of the loop body's first statement, which begins at line "
    "88; evaluations of the loop condition that do not enter the body are not "
    "iterations, and repeated executions are counted without deduplication. Return "
    "exactly a JSON object with the single key `loop_iteration_count`; its value "
    "must be the count as a raw JSON integer (not a quoted string)."
)

TRACE_RE = re.compile(
    r"\s(?P<file>\S*scrapy/utils/sitemap\.py):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def loop_body_line(source_path: Path) -> int:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        raise SystemExit(f"ERROR: cannot parse target source {source_path}: {exc}") from exc

    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_process_sitemap_element"
        ):
            loops = [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.While) and child.lineno == LOOP_HEADER_LINE
            ]
            if len(loops) != 1 or not loops[0].body:
                raise SystemExit(
                    f"ERROR: expected one while loop at {TARGET_FILE}:{LOOP_HEADER_LINE}"
                )
            return loops[0].body[0].lineno
    raise SystemExit(f"ERROR: target function not found in {source_path}")


def parse_iteration_count(trace_path: Path, body_line: int) -> int:
    if not trace_path.exists():
        raise SystemExit(f"ERROR: trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    events: list[tuple[int, str]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append((int(match.group("line")), match.group("event")))

    if not events:
        raise SystemExit(f"ERROR: trace contains zero events for {TARGET_FUNC}")

    invocation = 0
    active = False
    completed = False
    count = 0
    for line_number, event in events:
        if event == "call":
            invocation += 1
            active = invocation == 1
            continue
        if active and event == "line" and line_number == body_line:
            count += 1
        if active and event == "return":
            completed = True
            active = False
            break

    if invocation == 0:
        raise SystemExit(f"ERROR: no call event found for {TARGET_FUNC}")
    if not completed:
        raise SystemExit(f"ERROR: invocation 1 of {TARGET_FUNC} has no return event")
    if count == 0:
        raise SystemExit(
            f"ERROR: invocation 1 executed no loop-body events at {TARGET_FILE}:{body_line}"
        )
    return count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    body_line = loop_body_line(Path(TARGET_FILE))
    if body_line != 88:
        raise SystemExit(
            f"ERROR: expected loop body to begin at {TARGET_FILE}:88, found {body_line}"
        )

    answer = parse_iteration_count(args.trace_log, body_line)
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": answer},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
