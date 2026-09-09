#!/usr/bin/env python3
"""Parse trace log into M7_Invariants oracle for rich.containers.Lines.justify."""

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
TARGET_FILE = "rich/containers.py"
TARGET_FUNC = "rich.containers.Lines.justify"
DEF_LINE = 111
TEST_CLASS = (
    "rich_qa/containers_justify_m7_invariants/files/testcase.py::"
    "ContainersJustifyInvariantsTest"
)

TEST_METHODS = [
    "test_center_justify_overflow_ellipsis_iota",
    "test_center_justify_various_theta",
    "test_full_justify_dense_words_alpha",
    "test_full_justify_dense_words_beta",
    "test_full_justify_mixed_lengths_zeta",
    "test_full_justify_narrow_width_gamma",
    "test_full_justify_overflow_crop_eta",
    "test_full_justify_single_token_lines",
    "test_full_justify_styled_words_delta",
    "test_full_justify_styled_words_epsilon",
    "test_right_justify_overflow_fold_lambda",
    "test_right_justify_various_kappa",
]

QUESTION = f"""\
During pytest run {TEST_CLASS}, aggregate invariant observations across all twelve test methods in that class (every def test_... method), in pytest collection order: {", ".join(TEST_METHODS)}.

The tests call {TARGET_FUNC} directly in rich/containers.py (the def statement begins on line {DEF_LINE}). Consider only trace events whose func equals {TARGET_FUNC} exactly (module-qualified dotted name).

An invocation is one call event for justify at line {DEF_LINE}, in chronological order across the whole test run. For each invocation, walk every trace event for that frame until its matching return event, merging locals as follows: start from the locals= mapping on the call event; for each subsequent event in the same frame before return, for every name that appears in that event's locals= mapping, replace the stored value with the new logged value (names not listed keep their previous value). This merged mapping is the evaluation environment for observations in that invocation.

Each observation is one line event with event=line whose absolute 1-based line number in {TARGET_FILE} matches the predicate's observation line. Python's trace hook delivers line events immediately before the named line executes; evaluate the predicate on the merged environment after applying that event's locals= overrides. The def line ({DEF_LINE}), decorator lines, and docstring lines are not executable and never produce observations. Multi-line statements report the line where the statement begins.

For each candidate predicate below, count observations and violations across every matching line event in every invocation and every test method. violations is how many evaluations were false; held_always is true only when violations equals zero and observations is greater than zero. When observations is zero (the observation line never executed), report observations=0, violations=0, and held_always=false.

Logged local values are Python repr strings as written in the trace (for example an int appears as its decimal numeral without quotes, a str parameter appears wrapped in single quotes inside the repr). To obtain a Text plain string from a logged line value, take the substring between the first <text ' and the following ' in the repr (if that pattern is absent, plain length is zero). For ASCII plain text in this test run, cell length equals len(plain). Parse list and int locals with ast.literal_eval on the logged repr string.

Sort the invariant_report list by predicate ascending (Unicode code-point order). Tie-break: none needed beyond predicate string.

Report JSON with top-level key invariant_report whose value is a list of objects, each with exactly these keys:
- predicate (str): one of the candidate predicates stated verbatim below
- held_always (bool)
- observations (int)
- violations (int)

Candidate predicates (evaluate exactly as written; observation line follows):

1. Predicate "cell_len(line.plain) is at most width at the center pad_right step" — observation line 137. True when len(plain) extracted from line as above is less than or equal to width parsed as int.

2. Predicate "overflow is crop fold or ellipsis" — observation line 131. True when overflow parsed with ast.literal_eval is one of the strings crop, fold, or ellipsis.

3. Predicate "sum of spaces equals num_spaces" — observation line 156. True when sum of the list obtained by ast.literal_eval from spaces equals num_spaces parsed as int.

4. Predicate "width is at least fifteen" — observation line 146. True when width parsed as int is greater than or equal to fifteen.

5. Predicate "words_size is strictly less than width" — observation line 153. True when words_size parsed as int is strictly less than width parsed as int.

6. Predicate "words_size plus num_spaces is at most width" — observation line 153. True when words_size plus num_spaces (both ints from their logged repr strings) is less than or equal to width parsed as int.\
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

TEXT_PLAIN_RE = re.compile(r"<text '([^']*)'")


@dataclass(frozen=True)
class PredicateSpec:
    predicate: str
    observation_line: int
    evaluate: Callable[[dict[str, str]], bool]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def _parse_int(name: str, state: dict[str, str]) -> int:
    return int(state[name])


def _parse_list(name: str, state: dict[str, str]) -> list[int]:
    value = ast.literal_eval(state[name])
    if not isinstance(value, list):
        raise ValueError(f"{name} is not a list: {state[name]!r}")
    return [int(item) for item in value]


def _plain_from_line(state: dict[str, str]) -> str:
    match = TEXT_PLAIN_RE.search(state["line"])
    return match.group(1) if match else ""


def _predicate_center_cell_len(state: dict[str, str]) -> bool:
    plain = _plain_from_line(state)
    width = _parse_int("width", state)
    return len(plain) <= width


def _predicate_overflow_enum(state: dict[str, str]) -> bool:
    overflow = ast.literal_eval(state["overflow"])
    return overflow in {"crop", "fold", "ellipsis"}


def _predicate_sum_spaces(state: dict[str, str]) -> bool:
    spaces = _parse_list("spaces", state)
    num_spaces = _parse_int("num_spaces", state)
    return sum(spaces) == num_spaces


def _predicate_words_plus_spaces_le_width(state: dict[str, str]) -> bool:
    words_size = _parse_int("words_size", state)
    num_spaces = _parse_int("num_spaces", state)
    width = _parse_int("width", state)
    return words_size + num_spaces <= width


def _predicate_words_lt_width(state: dict[str, str]) -> bool:
    words_size = _parse_int("words_size", state)
    width = _parse_int("width", state)
    return words_size < width


def _predicate_width_at_least_fifteen(state: dict[str, str]) -> bool:
    return _parse_int("width", state) >= 15


PREDICATES: list[PredicateSpec] = [
    PredicateSpec(
        "cell_len(line.plain) is at most width at the center pad_right step",
        137,
        _predicate_center_cell_len,
    ),
    PredicateSpec(
        "overflow is crop fold or ellipsis",
        131,
        _predicate_overflow_enum,
    ),
    PredicateSpec(
        "sum of spaces equals num_spaces",
        156,
        _predicate_sum_spaces,
    ),
    PredicateSpec(
        "width is at least fifteen",
        146,
        _predicate_width_at_least_fifteen,
    ),
    PredicateSpec(
        "words_size is strictly less than width",
        153,
        _predicate_words_lt_width,
    ),
    PredicateSpec(
        "words_size plus num_spaces is at most width",
        153,
        _predicate_words_plus_spaces_le_width,
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

        if event == "call" and lineno == DEF_LINE:
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
