import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


TARGET_FILE = "scripts/sponsors.py"
TARGET_FUNC = "scripts.sponsors.main"
OBSERVATION_LINE = 171

EVENT_RE = re.compile(
    r" (?P<file>\S+scripts/sponsors\.py):(?P<line>\d+) "
    r"(?P<func>scripts\.sponsors\.main) event=(?P<event>\w+)"
    r".* locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run only the pytest test
`fastapi_qa/sponsors_main_m7_invariants/files/testcase.py::TestSponsorsMainInvariants::test_seeded_tiers_reach_unchanged_content_exit`.
For `scripts.sponsors.main` in the repository-relative file `scripts/sponsors.py`,
check the candidate predicate
`key % (len(keys) - keys.index(key) + 1) != 0`
at every outer-loop observation point.

An outer-loop observation is each execution of the line event for absolute,
1-based source line 171, immediately before the statement `sponsor_group = []`
executes. For a multi-line statement or expression, an executed-line event is
at the absolute, 1-based line where that statement or expression begins; the
function's `def` line, decorators, and non-executed comment lines are not
observations. Iteration N is the Nth execution of line 171, in chronological
order, across the run. An invocation means one Python call of
`scripts.sponsors.main`, numbered from 1 in chronological order; include
observations from every invocation made by this single test.

Evaluate the predicate with ordinary Python semantics using the target frame's
local values at that observation, before line 171 executes. In particular,
`keys.index(key)` is the zero-based index returned by Python list indexing.
Count every observation in chronological order, including repeated local
states; do not sort or deduplicate observations. A violating iteration is an
observation where the predicate evaluates to false. The invariant is always
held only when it is true at every observation. With zero observations it is
not evaluable: report `is_invariant_always_held` as false and both counts as
zero.

Return exactly one JSON object with these keys:
`is_invariant_always_held` (a JSON boolean),
`total_iterations_observed` (a non-negative base-10 JSON integer), and
`violating_iteration_count` (a non-negative base-10 JSON integer). Use exactly
those spellings. No values require `repr`, string, exception-name, function-name,
empty-value, or null serialization; the answer contains only the stated JSON
boolean and integers. The keys are fixed by this schema, and no sorting or
tie-breaking of answer entries applies."""


def parse_trace(trace_path: Path) -> dict[str, Any]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    state: dict[str, str] = {}
    target_event_count = 0
    total = 0
    violations = 0

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        target_event_count += 1

        try:
            changed_locals = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(changed_locals, dict):
            raise RuntimeError(f"target locals are not a dictionary: {raw_line}")
        state.update(changed_locals)

        if (
            match.group("event") != "line"
            or int(match.group("line")) != OBSERVATION_LINE
        ):
            continue

        if "key" not in state or "keys" not in state:
            raise RuntimeError(f"required locals missing at observation: {raw_line}")
        try:
            key = ast.literal_eval(state["key"])
            keys = ast.literal_eval(state["keys"])
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot decode predicate locals: {raw_line}") from exc
        if not isinstance(key, (int, float)) or not isinstance(keys, list):
            raise RuntimeError(f"predicate locals have unexpected types: {raw_line}")

        total += 1
        if not (key % (len(keys) - keys.index(key) + 1) != 0):
            violations += 1

    if target_event_count == 0:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    return {
        "is_invariant_always_held": total > 0 and violations == 0,
        "total_iterations_observed": total,
        "violating_iteration_count": violations,
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
