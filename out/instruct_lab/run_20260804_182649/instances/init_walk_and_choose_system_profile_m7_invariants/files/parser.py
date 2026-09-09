#!/usr/bin/env python3
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/instructlab/config/init.py"
TARGET_FUNC = "instructlab.config.init.walk_and_choose_system_profile"
OBSERVATION_LINE = 204
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    r".*\slocals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the complete pytest test `instruct_lab_qa/init_walk_and_choose_system_profile_m7_invariants/files/testcase.py::TestSystemProfileDiscovery::test_seeded_profile_catalog_walk` and consider exactly `instructlab.config.init.walk_and_choose_system_profile` in `src/instructlab/config/init.py`. At every observation point defined below, evaluate this candidate predicate verbatim using the target frame's current local values:

`(sum(ord(ch) for ch in str_chip_name) + len(system_profile_file) + gpus) % 97 != 0`

An invocation is one Python call entry into exactly the named target function, counted 1-based in chronological order during the complete test run. Calls of callees, nested functions, comprehensions, generators, or any other frame do not create target invocations. An observation point is each `line` event in the target's own frame at absolute line 204, immediately before Python evaluates the first comparison in the multi-line `if` condition whose opening parenthesis is on line 203. Thus, iteration N is the Nth chronological execution of line 204 across all target invocations; count repeated executions separately, without sorting or deduplication. Do not inspect events or local values from any other frame.

Line 204 means the 1-based physical line in the named repository file as it exists for this test. For a multi-line statement or expression, an executed-line event is associated with the physical line where the particular executed subexpression begins; here, the condition's first comparison begins on line 204 even though the `if (` begins on line 203. Continuation-only text does not by itself create another observation. The `def` line, decorator lines, comments, docstring text, and unexecuted lines are not observations. At each observation, use the already-bound current values of `str_chip_name`, `system_profile_file`, and `gpus` from that target frame. Parameters are bound on call entry; ordinary assignment binds after the assignment executes, and augmented assignment both reads and writes its target. Comprehension-local variables belong to their separate comprehension frame and are excluded. Evaluate `sum`, `ord`, `len`, `%`, `+`, and `!=` with their ordinary Python semantics; do not use `repr()`, `str()`, JSON coercion, or values from earlier observations in place of the current values.

The predicate “held at every observation” exactly when its Python result was `True` at every counted observation. `total_iterations_observed` is the number of counted line-204 events, and `violating_iteration_count` is the number of those events at which the result was `False`. If there are zero observations, report `is_invariant_always_held` as `false` and both counts as `0`; otherwise report it as `true` exactly when the violating count is zero.

Return exactly one JSON object with the canonical shape `{"is_invariant_always_held": bool, "total_iterations_observed": int, "violating_iteration_count": int}`. The first value is a JSON boolean and the two counts are non-negative JSON integers. Preserve the key spellings exactly. There are no reported function names, line numbers, variable values, strings, lists, nulls, or omitted values, and no output ordering or tie-breaking beyond the fixed object keys."""


def parse_answer(trace_path: Path) -> dict[str, bool | int]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocations = 0
    active = False
    state: dict[str, str] = {}
    line_counts: Counter[int] = Counter()
    total = 0
    violations = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.match(raw_line)
        if not match:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue

        target_events += 1
        event = match.group("event")
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise RuntimeError(f"cannot parse target locals: {raw_line}") from exc
        if not isinstance(changed, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed.items()
        ):
            raise RuntimeError("target locals are not a string-to-string mapping")

        if event == "call":
            if active:
                raise RuntimeError("nested target invocation is unsupported")
            invocations += 1
            active = True
            state = dict(changed)
        elif not active:
            raise RuntimeError("target event occurred outside an active invocation")
        else:
            state.update(changed)

        if event == "line":
            line_number = int(match.group("line"))
            line_counts[line_number] += 1
            if line_number == OBSERVATION_LINE:
                required = ("str_chip_name", "system_profile_file", "gpus")
                missing = [name for name in required if name not in state]
                if missing:
                    raise RuntimeError(
                        f"observation is missing target locals: {', '.join(missing)}"
                    )
                try:
                    str_chip_name = ast.literal_eval(state["str_chip_name"])
                    system_profile_file = ast.literal_eval(state["system_profile_file"])
                    gpus = ast.literal_eval(state["gpus"])
                except (SyntaxError, ValueError) as exc:
                    raise RuntimeError("cannot decode predicate local values") from exc
                if not isinstance(str_chip_name, str):
                    raise RuntimeError("str_chip_name is not a string")
                if not isinstance(system_profile_file, str):
                    raise RuntimeError("system_profile_file is not a string")
                if not isinstance(gpus, int) or isinstance(gpus, bool):
                    raise RuntimeError("gpus is not an integer")

                held = (
                    sum(ord(ch) for ch in str_chip_name)
                    + len(system_profile_file)
                    + gpus
                ) % 97 != 0
                total += 1
                violations += int(not held)

        if event == "return":
            active = False
            state = {}

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active:
        raise RuntimeError("trace ended during an active target invocation")
    if invocations == 0:
        raise RuntimeError("trace contains zero target invocations")
    if sum(line_counts.values()) < 60:
        raise RuntimeError("target trace contains fewer than 60 line events")
    if len(line_counts) < 8:
        raise RuntimeError("target trace contains fewer than 8 distinct executed lines")
    if not line_counts or max(line_counts.values()) < 20:
        raise RuntimeError("no target line executed at least 20 times")
    if total < 20:
        raise RuntimeError(f"expected at least 20 predicate observations, found {total}")

    return {
        "is_invariant_always_held": violations == 0,
        "total_iterations_observed": total,
        "violating_iteration_count": violations,
    }


def main() -> int:
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
        "oracle_answer": parse_answer(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
