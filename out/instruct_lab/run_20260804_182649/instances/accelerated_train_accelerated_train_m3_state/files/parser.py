#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


TARGET_FILE = "src/instructlab/model/accelerated_train.py"
TARGET_FUNC = "instructlab.model.accelerated_train.accelerated_train"
VARIABLE = "journal"
TRACE_RE = re.compile(
    r"^\S+\s+\S+\s+(?P<file>.+?):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
    r".*\slocals=(?P<locals>\{.*\})$"
)

QUESTION = """Run the pytest test `instruct_lab_qa/accelerated_train_accelerated_train_m3_state/files/testcase.py::TestAcceleratedPipeline::test_seeded_phased_journals` and consider exactly `instructlab.model.accelerated_train.accelerated_train` in `src/instructlab/model/accelerated_train.py`. Across every invocation of that function during the complete test run, what is the sorted set of distinct Python `repr()` strings taken by the local variable `journal` at the observation points defined below?

An invocation is one Python function-call entry into exactly `instructlab.model.accelerated_train.accelerated_train`, counted 1-based in chronological order over the complete test run. Calls of nested functions, callees, comprehensions, generators, or any other frame do not create target invocations. Include every target invocation, from the first call entry through its normal return or an exception leaving the frame.

Within each target invocation, observation points are: (1) function-call entry, after parameters have been bound; (2) immediately before each executed source line in that target frame; (3) when an exception has just been raised into that target frame, before its handler runs or it propagates; and (4) function return, after the function body has completed and immediately before control returns to the caller. Observe only the target's own frame, not activity in callees. Record a value only when `journal` is already bound at that observation point. If a callee mutates the object referenced by `journal` in place, its changed whole-object representation is therefore first observed at the next target-frame observation point.

Line numbers governing source-line observations are absolute, 1-based physical lines in the named file as it exists in the repository. For a multi-line statement or expression, use the physical line where the particular executed statement or expression begins; a continuation-only line does not create an extra observation merely because it contains text. A multi-line call can still produce observations on later lines when separately executed argument expressions begin there. The `def` line, decorator lines, and unexecuted comment or docstring lines are not source-line observation points merely because they exist in the file. Parameters count as bound at call entry, while a local assigned later (including by ordinary or augmented assignment) does not count as bound until Python has performed that assignment; augmented assignment both reads and writes its target. Comprehension-local variables belong to the comprehension frame and are excluded.

For every included observation, apply Python `repr()` to the current value of `journal`, not `str()` and not JSON serialization. For a container, this is the `repr()` of the whole container, including Python spellings such as `None` and `True`; for example, a hypothetical value could be represented by the JSON string `"['alpha', None]"`. Preserve every character returned by `repr()`; if it contains a newline, JSON encodes that newline normally. Deduplicate equal repr strings across all points and invocations, then sort the remaining strings in ascending lexicographic Unicode code-point order, with ordinary prefix ordering (a proper prefix sorts first). Do not perform numeric or natural sorting.

Return exactly one JSON object with the canonical shape `{"unique_values": ["str"]}`. In the actual answer, `unique_values` is the sorted list just defined; each element is a JSON string containing one Python repr string. Every observation that contributes a list element has `journal` bound and produces a non-empty repr string; JSON `null`, an empty string, and an absent list element are not substitutes. No function names, exception type names, line numbers, invocation numbers, or raw non-string values are reported."""


def parse_unique_values(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_events = 0
    invocations = 0
    active = False
    state: dict[str, str] = {}
    values: set[str] = set()
    line_counts: Counter[int] = Counter()

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
            invocations += 1
            active = True
            state = dict(changed)
        elif active:
            state.update(changed)
        else:
            raise RuntimeError("target event occurred outside an active invocation")

        if event == "line":
            line_counts[int(match.group("line"))] += 1
        if VARIABLE in state:
            values.add(state[VARIABLE])
        if event == "return":
            active = False
            state = {}

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active:
        raise RuntimeError("trace ended during an active target invocation")
    if invocations < 2:
        raise RuntimeError(f"expected multiple target invocations, found {invocations}")
    if sum(line_counts.values()) < 60:
        raise RuntimeError("target trace contains fewer than 60 line events")
    if len(line_counts) < 8:
        raise RuntimeError("target trace contains fewer than 8 distinct executed lines")
    if not line_counts or max(line_counts.values()) < 5:
        raise RuntimeError("no target line executed at least 5 times")
    if len(values) < 8:
        raise RuntimeError(
            f"expected at least 8 distinct repr values for {VARIABLE}, found {len(values)}"
        )
    return sorted(values)


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": {"unique_values": parse_unique_values(args.trace_log)},
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
