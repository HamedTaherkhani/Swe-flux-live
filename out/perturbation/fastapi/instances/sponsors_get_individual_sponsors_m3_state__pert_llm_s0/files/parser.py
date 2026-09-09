from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE_SUFFIX = "/scripts/sponsors.py"
TARGET_FUNC = "scripts.sponsors.get_individual_sponsors"
OBSERVATION_LINES = {134, 136}

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)(?P<rest>.*)$"
)

QUESTION = (
    "Run only the pytest test "
    "`fastapi_qa/sponsors_get_individual_sponsors_m3_state/files/testcase.py::"
    "TestSponsorsProgramState::test_main_collects_generated_sponsor_pages`. "
    "For every invocation of `scripts.sponsors.get_individual_sponsors` in "
    "`scripts/sponsors.py`, observe the function frame at each Python "
    "executed-line event on absolute, 1-based source lines 134 and 136. An "
    "invocation is one call of that exact function, numbered 1-based in "
    "chronological call order; include observations from all invocations. A "
    "line event occurs after effects of previously executed statements are "
    "visible and immediately before the statement or expression beginning on "
    "the reported line executes. For a multi-line statement, its event line "
    "is the line where that statement or expression begins. Only these two "
    "body lines count; the function's `def` line, decorators, and docstring "
    "lines do not count. At every included event, form a two-element Python "
    "tuple whose first element is the current local variable `nodes` and whose "
    "second element is the current local variable `edges`, then take `repr()` "
    "of the whole tuple (not `str()` and not separate representations). Thus "
    "containers and their nested values use standard Python representations, "
    "including Python spellings such as `None` and `True` if present. Remove "
    "duplicate representation strings across all included events, then sort "
    "the remaining strings in ascending lexicographic order using Python's "
    "normal string ordering (Unicode code-point order, with no secondary "
    "tie-breaker needed after deduplication). Return exactly "
    "`{\"unique_values\": [...]}`, where the value is the sorted JSON array "
    "of those Python `repr()` strings; each array element is a JSON string, "
    "and no observation is represented by JSON null or by an omitted entry."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def parse_changed_locals(rest: str, line_number: int) -> dict[str, str]:
    marker = " locals="
    if marker not in rest:
        raise RuntimeError(f"target event on trace line {line_number} has no locals field")
    raw = rest.rsplit(marker, 1)[1]
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError(
            f"cannot parse locals on trace line {line_number}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"locals on trace line {line_number} are not a dictionary")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise RuntimeError(
            f"locals on trace line {line_number} do not contain repr strings"
        )
    return value


def collect_unique_values(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    state: dict[str, str] = {}
    values: set[str] = set()
    target_events = 0

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
        changed = parse_changed_locals(match.group("rest"), trace_line_number)
        state.update(changed)

        source_line = int(match.group("line"))
        if match.group("event") != "line" or source_line not in OBSERVATION_LINES:
            continue
        if "nodes" not in state or "edges" not in state:
            raise RuntimeError(
                f"missing nodes or edges state at target source line {source_line}"
            )
        values.add(f"({state['nodes']}, {state['edges']})")

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in scripts/sponsors.py"
        )
    if not values:
        raise RuntimeError(
            f"trace contains no observations on target lines {sorted(OBSERVATION_LINES)}"
        )
    return sorted(values)


def main() -> None:
    args = parse_args()
    unique_values = collect_unique_values(args.trace_log)
    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": unique_values},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.out} with {len(unique_values)} unique state values")


if __name__ == "__main__":
    main()
