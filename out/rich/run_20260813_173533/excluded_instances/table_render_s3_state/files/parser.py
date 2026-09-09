"""Parse trace log into S3_ProgramState oracle for table_render_s3_state."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

TARGET_FILE = "rich/table.py"
TARGET_FUNC = "rich.table.Table._render"
ENTRY_LINE = 755
SOURCE_LINE_AFTER = 846
ANCHOR_LINE = 848
TARGET_K = 15
FINAL_RETURN_LINE = 935
TARGET_INVOCATION = 1
VARIABLES = [
    "end_section",
    "first",
    "footer_row",
    "header_row",
    "index",
    "last",
    "max_height",
    "row",
    "row_height",
]

LINE_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<path>.+?):(?P<lineno>\d+) "
    r"(?P<func>[^\s]+) "
    r"event=(?P<event>\w+)"
    r"(?: retval=(?P<retval>.*?))?"
    r"(?: exc=(?P<exc>.*?))?"
    r" locals=(?P<locals>\{.*\})$"
)


def _parse_locals(raw: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Failed to parse locals dict: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("locals payload is not a dict")
    return {str(k): str(v) for k, v in parsed.items()}


def _build_question() -> str:
    return (
        "During pytest run "
        "`rich_qa/table_render_s3_state/files/testcase.py::"
        "TableRenderS3StateTest::test_table_render_state_harvest`, "
        "consider the 1st invocation of `rich.table.Table._render` in "
        "`rich/table.py` (count invocations by chronological entry at "
        "physical line 755; suspend/resume via `yield` inside the generator "
        "does not start a new invocation; the invocation ends when the "
        "generator is exhausted). Line numbers are absolute, 1-based, in "
        "`rich/table.py` as checked into the repository; a `line` trace event "
        "fires immediately before that physical source line begins executing "
        "(for a multi-line statement, the line where the statement starts). "
        "Immediately after physical line 846 (`row_height = max(len(cell) for "
        "cell in cells)`) has finished executing for the 15th time during "
        "that invocation, what are the values of the local variables "
        "`end_section`, `first`, `footer_row`, `header_row`, `index`, `last`, "
        "`max_height`, `row`, and `row_height` bound in the `Table._render` "
        "frame? Because `Table._render` is a generator function, `yield` "
        "expressions suspend execution but do not end the invocation; only "
        "the final `return` when the generator is exhausted ends it. Count "
        "completions of line 846 as the 1st, 2nd, … times Python finishes "
        "executing that statement during the invocation (each pass through "
        "the outer `for index, (first, last, row_cell) in "
        "enumerate(loop_first_last(row_cells))` loop produces one completion "
        "after all cells in that row are rendered). The observation moment is "
        "right after the 15th such completion and before any later statement in "
        "`Table._render` runs for that row (in particular, before the nested "
        "`def align_cell` on line 848 begins). At that moment, report the "
        "current binding of each listed name in the `Table._render` local "
        "namespace (names not yet rebound in the current row iteration retain "
        "their values from earlier in the same invocation). Report each value "
        "as the Python `repr()` string (for example, `repr(3)` is `'3'` and "
        "`repr(False)` is `'False'`; containers use the `repr` of the whole "
        "container). If a listed variable is not yet bound, report the JSON "
        "(only if truly unbound). Return JSON matching `template_answer`: "
        "`observed_state` is a list of objects with keys `variable` and "
        "`value`, sorted ascending by `variable` (lexicographic on the variable "
        "name), containing exactly the nine variables named above."
    )


def _extract_observed_state(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.is_file():
        raise SystemExit(f"Trace log not found: {trace_path}")

    raw_lines = trace_path.read_text(encoding="utf-8").splitlines()
    if not raw_lines:
        raise SystemExit(f"Trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    in_invocation = False
    accumulated: dict[str, str] = {}
    prev_lineno: int | None = None
    post_846_count = 0
    observed: dict[str, str] | None = None

    for raw in raw_lines:
        if "event=" not in raw or TARGET_FILE not in raw.replace("\\", "/"):
            continue
        match = LINE_EVENT_RE.match(raw)
        if not match:
            continue
        func = match.group("func")
        if func != TARGET_FUNC:
            continue

        event = match.group("event")
        lineno = int(match.group("lineno"))
        target_events += 1

        if event == "call":
            if lineno == ENTRY_LINE:
                invocation += 1
                if invocation == TARGET_INVOCATION:
                    in_invocation = True
                    accumulated = {}
                    prev_lineno = None
                    post_846_count = 0
            continue

        if event == "return" and in_invocation:
            retval = match.group("retval")
            if lineno == FINAL_RETURN_LINE and retval == "None":
                in_invocation = False
            continue

        if not in_invocation or event != "line":
            continue

        changed = _parse_locals(match.group("locals"))
        if prev_lineno == SOURCE_LINE_AFTER and lineno == ANCHOR_LINE:
            post_846_count += 1
            accumulated.update(changed)
            if post_846_count == TARGET_K:
                observed = dict(accumulated)
        else:
            accumulated.update(changed)
        prev_lineno = lineno

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if invocation < TARGET_INVOCATION:
        raise SystemExit(
            f"Expected at least {TARGET_INVOCATION} invocations; saw {invocation}"
        )
    if observed is None:
        raise SystemExit(
            f"Observation point not reached: line {SOURCE_LINE_AFTER} "
            f"completed {post_846_count} times, need {TARGET_K}"
        )

    result: list[dict[str, str]] = []
    for name in VARIABLES:
        if name not in observed:
            raise SystemExit(f"Variable {name!r} missing at observation point")
        result.append({"variable": name, "value": observed[name]})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    observed_state = _extract_observed_state(Path(args.trace_log))
    oracle = {
        "question_kind": "S3_ProgramState",
        "question": _build_question(),
        "template_answer": {
            "observed_state": [{"variable": "str", "value": "str"}],
        },
        "oracle_answer": {"observed_state": observed_state},
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
