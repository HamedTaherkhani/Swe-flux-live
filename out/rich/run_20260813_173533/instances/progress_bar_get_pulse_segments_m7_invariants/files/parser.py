#!/usr/bin/env python3
"""Parse trace log into M7_Invariants oracle for ProgressBar._get_pulse_segments."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

QUESTION_KIND = "M7_Invariants"
TARGET_FILE = "rich/progress_bar.py"
TARGET_FUNC = "rich.progress_bar.ProgressBar._get_pulse_segments"
PULSE_SIZE = 20
TEST_CLASS = (
    "rich_qa/progress_bar_get_pulse_segments_m7_invariants/files/testcase.py::"
    "ProgressBarGetPulseSegmentsInvariantsTest"
)

TEST_METHODS = [
    "test_ascii_false_zeta",
    "test_ascii_true_epsilon",
    "test_back_without_color_iota",
    "test_complement_pairs_lambda",
    "test_deep_batch_kappa",
    "test_eight_bit_palette_delta",
    "test_fore_without_color_theta",
    "test_hue_sweep_mu",
    "test_mixed_ascii_calls_eta",
    "test_standard_palette_gamma",
    "test_truecolor_batch_alpha",
    "test_truecolor_batch_beta",
]

QUESTION = f"""\
During pytest run {TEST_CLASS}, aggregate invariant observations across all twelve test methods in that class (every def test_... method), in pytest collection order: {", ".join(TEST_METHODS)}.

The tests call {TARGET_FUNC} directly in {TARGET_FILE} (the def statement begins on line 70). Consider only trace events whose func equals {TARGET_FUNC} exactly (module-qualified dotted name).

An invocation is one call event for _get_pulse_segments, in chronological order across the whole test run. For each invocation, walk every trace event for that frame until its matching return event, merging locals as follows: start from the locals= mapping on the call event; for each subsequent event in the same frame before return, for every name that appears in that event's locals= mapping, replace the stored value with the new logged value (names not listed keep their previous value). This merged mapping is the evaluation environment for observations in that invocation.

Each observation is one line event with event=line whose absolute 1-based line number in {TARGET_FILE} matches the predicate's observation line. Python's trace hook delivers line events immediately before the named line executes; evaluate the predicate on the merged environment after applying that event's locals= overrides. The def line (70), decorator lines, and docstring lines are not executable and never produce observations. Multi-line statements report the line where the statement begins.

For each candidate predicate below, count observations and violations across every matching line event in every invocation and every test method. violations is how many evaluations were false; held_always is true only when violations equals zero and observations is greater than zero. When observations is zero (the observation line never executed), report observations=0, violations=0, and held_always=false.

Logged local values are Python repr strings as written in the trace (for example an int appears as its decimal numeral without quotes, a bool appears as True or False without quotes, and a str appears wrapped in single quotes inside the repr). Parse bool, int, float, and list locals with ast.literal_eval on the logged repr string.

Sort the invariant_report list by predicate ascending (Unicode code-point order). Tie-break: none needed beyond predicate string.

Report JSON with top-level key invariant_report whose value is a list of objects, each with exactly these keys:
- predicate (str): one of the candidate predicates stated verbatim below
- held_always (bool)
- observations (int)
- violations (int)

Candidate predicates (evaluate exactly as written; observation line follows):

1. Predicate "ascii is false" — observation line 83. True when ascii parsed with ast.literal_eval is False.

2. Predicate "fade is at least one half" — observation line 112. True when fade parsed with ast.literal_eval as float is greater than or equal to 0.5.

3. Predicate "fade is between zero and one inclusive" — observation line 112. True when fade parsed with ast.literal_eval as float is greater than or equal to 0.0 and less than or equal to 1.0.

4. Predicate "index is even" — observation line 110. True when index parsed with ast.literal_eval as int is divisible by two.

5. Predicate "len(segments) equals PULSE_SIZE at early return" — observation line 90. True when len of the list obtained by ast.literal_eval from segments equals twenty (the module constant PULSE_SIZE in {TARGET_FILE}).

6. Predicate "position is strictly less than one half" — observation line 111. True when position parsed with ast.literal_eval as float is strictly less than 0.5.\
"""

TEMPLATE_ANSWER = {
    "invariant_report": [
        {
            "held_always": "bool",
            "observations": "int",
            "predicate": "str",
            "violations": "int",
        },
    ],
}

TRACE_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} )?"
    r"(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?"
    r"(?:\s+exc=(?P<exc>.*?))?"
    r"\s+locals=(?P<locals>\{.*\})\s*$"
)


@dataclass(frozen=True)
class PredicateSpec:
    predicate: str
    observation_line: int
    evaluate: Callable[[dict[str, str]], bool]


def _normalize_file(path: str) -> str:
    normalized = path.replace("\\", "/")
    idx = normalized.rfind(TARGET_FILE)
    if idx == -1:
        raise ValueError(f"trace path does not contain {TARGET_FILE!r}: {path!r}")
    return normalized[idx:]


def _parse_locals(raw: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"could not parse locals dict: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"locals is not a dict: {raw!r}")
    return {str(key): str(value) for key, value in parsed.items()}


def _parse_bool(name: str, state: dict[str, str]) -> bool:
    value = ast.literal_eval(state[name])
    if not isinstance(value, bool):
        raise ValueError(f"{name} is not a bool: {state[name]!r}")
    return value


def _parse_int(name: str, state: dict[str, str]) -> int:
    return int(ast.literal_eval(state[name]))


def _parse_float(name: str, state: dict[str, str]) -> float:
    return float(ast.literal_eval(state[name]))


def _parse_list(name: str, state: dict[str, str]) -> list[object]:
    value = ast.literal_eval(state[name])
    if not isinstance(value, list):
        raise ValueError(f"{name} is not a list: {state[name]!r}")
    return value


def _predicate_ascii_false(state: dict[str, str]) -> bool:
    return not _parse_bool("ascii", state)


def _predicate_fade_at_least_half(state: dict[str, str]) -> bool:
    return _parse_float("fade", state) >= 0.5


def _predicate_fade_in_unit_interval(state: dict[str, str]) -> bool:
    fade = _parse_float("fade", state)
    return 0.0 <= fade <= 1.0


def _predicate_index_even(state: dict[str, str]) -> bool:
    return _parse_int("index", state) % 2 == 0


def _predicate_early_return_segment_count(state: dict[str, str]) -> bool:
    segments = _parse_list("segments", state)
    return len(segments) == PULSE_SIZE


def _predicate_position_lt_half(state: dict[str, str]) -> bool:
    return _parse_float("position", state) < 0.5


PREDICATES: list[PredicateSpec] = [
    PredicateSpec("ascii is false", 83, _predicate_ascii_false),
    PredicateSpec("fade is at least one half", 112, _predicate_fade_at_least_half),
    PredicateSpec(
        "fade is between zero and one inclusive",
        112,
        _predicate_fade_in_unit_interval,
    ),
    PredicateSpec("index is even", 110, _predicate_index_even),
    PredicateSpec(
        "len(segments) equals PULSE_SIZE at early return",
        90,
        _predicate_early_return_segment_count,
    ),
    PredicateSpec(
        "position is strictly less than one half",
        111,
        _predicate_position_lt_half,
    ),
]


def _split_trace_line(line: str) -> tuple[str, int, str, str, dict[str, str]] | None:
    match = TRACE_LINE_RE.match(line.strip())
    if not match:
        return None
    file_path = _normalize_file(match.group("file"))
    if file_path != TARGET_FILE:
        return None
    func = match.group("func")
    if func != TARGET_FUNC:
        return None
    event = match.group("event")
    lineno = int(match.group("line"))
    locals_dict = _parse_locals(match.group("locals"))
    return file_path, lineno, func, event, locals_dict


def _evaluate_predicate(spec: PredicateSpec, state: dict[str, str]) -> bool:
    try:
        return spec.evaluate(state)
    except (KeyError, ValueError, TypeError):
        return False


def _collect_invariant_report(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.is_file():
        raise SystemExit(f"trace log not found: {trace_path}")

    raw_text = trace_path.read_text(encoding="utf-8")
    if not raw_text.strip():
        raise SystemExit(f"trace log is empty: {trace_path}")

    stats = {
        spec.predicate: {"observations": 0, "violations": 0}
        for spec in PREDICATES
    }
    target_events = 0
    active_state: dict[str, str] | None = None

    for line in raw_text.splitlines():
        if TARGET_FUNC not in line or TARGET_FILE not in line:
            continue
        parsed = _split_trace_line(line)
        if parsed is None:
            continue
        _file, lineno, _func, event, changed = parsed
        target_events += 1

        if event == "call":
            active_state = dict(changed)
            continue

        if active_state is None:
            continue

        if event == "return":
            active_state = None
            continue

        active_state.update(changed)

        if event != "line":
            continue

        for spec in PREDICATES:
            if lineno != spec.observation_line:
                continue
            stats[spec.predicate]["observations"] += 1
            if not _evaluate_predicate(spec, active_state):
                stats[spec.predicate]["violations"] += 1

    if target_events == 0:
        raise SystemExit(
            f"trace log contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    report: list[dict[str, object]] = []
    for spec in sorted(PREDICATES, key=lambda item: item.predicate):
        observations = stats[spec.predicate]["observations"]
        violations = stats[spec.predicate]["violations"]
        held_always = violations == 0 and observations > 0
        report.append(
            {
                "held_always": held_always,
                "observations": observations,
                "predicate": spec.predicate,
                "violations": violations,
            }
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    invariant_report = _collect_invariant_report(Path(args.trace_log))
    oracle = {
        "question_kind": QUESTION_KIND,
        "question": QUESTION,
        "template_answer": TEMPLATE_ANSWER,
        "oracle_answer": {"invariant_report": invariant_report},
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
