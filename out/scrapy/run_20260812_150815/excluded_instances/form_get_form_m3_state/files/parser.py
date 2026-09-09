from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/http/request/form.py"
TARGET_FUNC = "scrapy.http.request.form._get_form"
OBSERVATION_LINES = {199, 201}

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_unique_values(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_event_count = 0
    observations: list[str] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_event_count += 1
        if match.group("event") != "line":
            continue
        if int(match.group("line")) not in OBSERVATION_LINES:
            continue

        marker = " locals="
        marker_at = raw_line.find(marker, match.end())
        if marker_at < 0:
            fail(f"target line event has no locals mapping: {raw_line}")
        raw_locals = raw_line[marker_at + len(marker) :]
        try:
            locals_map = ast.literal_eval(raw_locals)
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse locals mapping {raw_locals!r}: {exc}")
        if not isinstance(locals_map, dict):
            fail(f"locals payload is not a mapping: {raw_locals!r}")

        value = locals_map.get("nodes")
        if value is not None:
            if not isinstance(value, str):
                fail(f"traced repr for nodes is not a string: {value!r}")
            observations.append(value)

    if target_event_count == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not observations:
        fail(
            "trace contains no nodes observations at target lines "
            f"{sorted(OBSERVATION_LINES)}"
        )

    return sorted(set(observations))


def question_text() -> str:
    return (
        "Run every pytest test method in "
        "`scrapy_qa/form_get_form_m3_state/files/testcase.py::"
        "TestGetFormProgramState` (all methods whose names begin with `test_`; "
        "pytest identifies each as that class node id followed by `::test_method_name`). "
        "Aggregate observations over all of those methods in the ascending "
        "lexicographic method-name order used to collect this `unittest.TestCase`; "
        "there is no ordering tie-breaker because method names are unique. During the "
        "complete run, consider every invocation of "
        "`scrapy.http.request.form._get_form` in "
        "`scrapy/http/request/form.py`. An invocation is one call of that function, "
        "counted 1-based in chronological execution order, although invocation "
        "numbers are not included in the answer. For each invocation, observe the "
        "target frame immediately before each executed statement or expression "
        "beginning on absolute, 1-based source line 199 and line 201 of that file. "
        "These are two separate observation points: include an observation each time "
        "either line executes, but only when the local variable `nodes` is already "
        "defined at that point. A line event is the state immediately before the "
        "statement or expression whose first physical source line has that number; "
        "for a multi-line statement it belongs to the line where the statement or "
        "expression begins. The function's `def` line, decorator lines, docstring "
        "line, call events, return events, and exception events are not observation "
        "points. At every qualifying point, take Python `repr(nodes)` of the whole "
        "container in its current state; this includes mutations made in place "
        "between the two points. Use Python spellings inside each repr string "
        "(`None`, `True`, and `False`, not JSON spellings), preserve quotes and all "
        "other repr punctuation exactly, and do not abbreviate or otherwise normalize "
        "the string. For example, a hypothetical list containing an unrelated string "
        "would contribute the string `['alpha']`. Remove duplicate repr strings only "
        "after collecting all qualifying observations across all invocations and test "
        "methods. Sort the remaining strings in ascending Python string order, i.e. "
        "lexicographically by Unicode code point with shorter-prefix-first behavior; "
        "there are no secondary tie-breakers because exact duplicates are removed. "
        "Return exactly one JSON object with the single key `unique_values`; its value "
        "is the sorted JSON array of those Python-repr strings. Do not include line "
        "numbers, invocation numbers, variable names, null placeholders, or any "
        "additional keys. If no point qualified, the array would be empty."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    answer = {"unique_values": parse_unique_values(Path(args.trace_log))}
    payload = {
        "question_kind": "M3_ProgramState",
        "question": question_text(),
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": answer,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
