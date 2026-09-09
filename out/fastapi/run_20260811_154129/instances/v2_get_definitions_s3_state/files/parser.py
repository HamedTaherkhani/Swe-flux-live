from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/fastapi/_compat/v2.py"
TARGET_FUNC = "fastapi._compat.v2.get_definitions"
OBSERVATION_LINE = 340

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)

QUESTION = (
    "Run only the pytest test "
    "`fastapi_qa/v2_get_definitions_s3_state/files/testcase.py::"
    "TestGetDefinitionsProgramState::test_generated_model_description_cleanup`. "
    "Consider the first invocation of `fastapi._compat.v2.get_definitions` in "
    "`fastapi/_compat/v2.py`; an invocation is one call of that exact function "
    "during the test run, numbered 1-based in chronological call order. Build "
    "the complete ordered history of local variable `item_description` "
    "immediately after absolute, 1-based source line 339 has executed each "
    "time in that invocation. Here, step 1 is the first completion of line "
    "339, step 2 is the second, and so on. Line 339 is the assignment statement "
    "beginning on that line; its right-hand side and assignment have completed "
    "at the observation point, before line 340 mutates `item_def`. For a "
    "multi-line statement or expression, a Python executed-line event is "
    "associated with the absolute, 1-based line on which that statement or "
    "expression begins. The function's `def` line, decorators, and docstring "
    "lines are not observations. Preserve chronological order, include every "
    "completion of line 339, do not sort, and do not remove duplicates. "
    "Represent each observed value with Python `repr()` (never `str()`), so "
    "strings retain their quote characters, containers would be represented "
    "by the `repr()` of the whole container, and Python spellings such as "
    "`None` and `True` would be used. Any embedded newline is represented "
    "according to Python `repr()` inside the string; JSON escaping is only "
    "the serialization of that exact repr text. No value is represented by "
    "JSON null or by an omitted entry. Return exactly "
    "`{\"value_history\": [{\"step\": 1, \"value\": \"...\"}, ...]}`: "
    "`value_history` is a JSON array, each `step` is the 1-based integer "
    "defined above, and each `value` is the corresponding JSON string "
    "containing the exact Python repr."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def parse_changed_locals(rest: str, trace_line_number: int) -> dict[str, str]:
    marker = " locals="
    if marker not in rest:
        raise RuntimeError(
            f"target event on trace line {trace_line_number} has no locals field"
        )
    raw_locals = rest.rsplit(marker, 1)[1]
    try:
        changed = ast.literal_eval(raw_locals)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(
            f"cannot parse locals on trace line {trace_line_number}: {exc}"
        ) from exc
    if not isinstance(changed, dict):
        raise RuntimeError(
            f"locals on trace line {trace_line_number} are not a dictionary"
        )
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in changed.items()
    ):
        raise RuntimeError(
            f"locals on trace line {trace_line_number} are not repr strings"
        )
    return changed


def collect_value_history(trace_path: Path) -> list[dict[str, int | str]]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocation = 0
    first_invocation_active = False
    history: list[dict[str, int | str]] = []

    for trace_line_number, raw_line in enumerate(
        trace_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = EVENT_RE.match(raw_line)
        if match is None:
            continue
        if (
            not match.group("file").replace("\\", "/").endswith(TARGET_FILE_SUFFIX)
            or match.group("func") != TARGET_FUNC
        ):
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            invocation += 1
            first_invocation_active = invocation == 1
            continue
        if not first_invocation_active:
            continue

        if event == "return":
            first_invocation_active = False
            continue
        if event != "line" or int(match.group("line")) != OBSERVATION_LINE:
            continue

        changed = parse_changed_locals(match.group("rest"), trace_line_number)
        value = changed.get("item_description")
        if value is None:
            raise RuntimeError(
                "item_description was not recorded immediately after source line 339 "
                f"(trace line {trace_line_number})"
            )
        history.append({"step": len(history) + 1, "value": value})

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in fastapi/_compat/v2.py"
        )
    if invocation == 0:
        raise RuntimeError(f"trace contains no call event for {TARGET_FUNC}")
    if not history:
        raise RuntimeError(
            "trace contains no item_description observations after source line 339"
        )
    return history


def main() -> None:
    args = parse_args()
    history = collect_value_history(args.trace_log)
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "value_history": [{"step": "int", "value": "str"}]
        },
        "oracle_answer": {"value_history": history},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.out} with {len(history)} observed values")


if __name__ == "__main__":
    main()
