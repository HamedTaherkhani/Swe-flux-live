#!/usr/bin/env python3
"""Parse trace log into oracle.json for debug_get_template_locals_m7_invariants."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/debug.py"
TARGET_FUNC = "jinja2.debug.get_template_locals"

OBS_LINE_FIRST_LOOP = 150
OBS_LINE_CTX_NONE = 141
OBS_LINE_SECOND_LOOP = 167

PREDICATES: dict[str, tuple[int, str]] = {
    "data equals an empty dict": (
        OBS_LINE_CTX_NONE,
        "data_empty",
    ),
    "len(name) is strictly greater than 8": (
        OBS_LINE_FIRST_LOOP,
        "len_gt_8",
    ),
    "len(name) is strictly less than 6": (
        OBS_LINE_SECOND_LOOP,
        "len_lt_6",
    ),
    "name equals context": (
        OBS_LINE_FIRST_LOOP,
        "eq_context",
    ),
    "name starts with l underscore": (
        OBS_LINE_FIRST_LOOP,
        "starts_l",
    ),
    "value is the missing singleton": (
        OBS_LINE_FIRST_LOOP,
        "is_missing",
    ),
}

QUESTION = """\
During the pytest run for test class \
`jinja_qa/debug_get_template_locals_m7_invariants/files/testcase.py::TestGetTemplateLocalsIndirect`, \
aggregate invariant observations across **all** `test_*` methods in that class. \
Methods are identified by their pytest node ids and are ordered chronologically as \
pytest executes them (unittest discovery order: ascending ASCII by method name).

The target function is `jinja2.debug.get_template_locals` defined in \
`src/jinja2/debug.py` (the `def get_template_locals` line is line 131 in that file \
as checked into this repository). It is reached **indirectly** when a template render \
raises and `Environment.handle_exception` rewrites the traceback via \
`rewrite_traceback_stack` → `fake_traceback`; none of the tests call \
`get_template_locals` directly.

For each candidate predicate below, evaluate it at the stated observation point on \
every qualifying trace event during the run. Count **observations** (how many times \
the predicate was evaluated) and **violations** (how many evaluations were false). \
Set `held_always` to true only when `violations` is zero and `observations` is \
greater than zero; when `observations` is zero the predicate was not evaluable and \
`held_always` must be false with `violations` zero.

**Observation points** (only events whose qualified function name is exactly \
`jinja2.debug.get_template_locals` and whose file path ends with \
`src/jinja2/debug.py` count):

1. **Line 150, `line` event** — the statement `if not name.startswith("l_") or value is missing:`. \
This line executes once per iteration of the `for name, value in real_locals.items()` loop; \
at each such event both locals `name` and `value` are bound. Line numbers are absolute, \
1-based, and refer to the file as it exists in the repository; the `line` event fires \
immediately before that statement executes.

2. **Line 167, `line` event** — the statement `if value is missing:`. This line executes \
once per iteration of the `for name, (_, value) in local_overrides.items()` loop; at each \
such event both locals `name` and `value` are bound.

3. **Line 141, `line` event** — the assignment `data = {}` on the branch where `ctx is None`. \
An observation counts only when local `data` is already bound in the frame at this event \
(which requires that branch to have been taken).

**Parsing traced locals:** each logged local value is the `repr()` string recorded in \
the trace's `locals={...}` mapping (the same serialization produced by the tracer's \
`repr()` call). For `name`, parse with `ast.literal_eval` to obtain the runtime `str`. \
For `value`, if the logged repr is exactly the seven-character token `missing` with no \
surrounding quote characters, treat the value as the Jinja `missing` singleton; otherwise \
the repr is opaque (predicates that only inspect `name` still apply).

**Candidate predicates** (evaluate verbatim):

- `data equals an empty dict` — at observation point 3 only; true when `data` parses as \
an empty dict via `ast.literal_eval` on its logged repr (for example `{}`).
- `len(name) is strictly greater than 8` — at observation point 1 only.
- `len(name) is strictly less than 6` — at observation point 2 only.
- `name equals context` — at observation point 1 only; true when the parsed `name` equals \
the four-character string `context`.
- `name starts with l underscore` — at observation point 1 only; true when the parsed \
`name` begins with the two-character prefix `l_`.
- `value is the missing singleton` — at observation point 1 only; true when the `value` \
local is the Jinja `missing` singleton (identity with `jinja2.utils.missing`, not the \
four-character string `missing`).

Return JSON with top-level key `invariant_report`: a list of objects \
`{predicate, held_always, observations, violations}`, one per candidate predicate above. \
Sort the list by `predicate` ascending (bytewise ASCII / `strcmp` order).\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _repo_relative_path(abs_path: str) -> str:
    normalized = abs_path.replace("\\", "/")
    marker = f"/{TARGET_REL_FILE}"
    idx = normalized.rfind(marker)
    if idx == -1:
        return normalized.lstrip("/")
    return normalized[idx + 1 :]


def _parse_one_literal(fragment: str) -> tuple[object, int]:
    fragment = fragment.lstrip()
    for end in range(1, len(fragment) + 1):
        candidate = fragment[:end]
        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            continue
        return value, end
    raise ValueError(f"unable to parse literal from {fragment[:80]!r}")


def _extract_quoted_repr(tail: str) -> str | None:
    if not tail or tail[0] != '"':
        return None
    i = 1
    while i < len(tail):
        if tail[i] == '"' and (i + 1 >= len(tail) or tail[i + 1] in ",}"):
            return tail[1:i]
        i += 1
    return None


def _extract_local_repr(locals_str: str, key: str) -> str | None:
    marker = f"'{key}': "
    start = locals_str.find(marker)
    if start == -1:
        return None
    tail = locals_str[start + len(marker) :]
    if not tail:
        return None
    if tail[0] == '"':
        quoted = _extract_quoted_repr(tail)
        if quoted is None:
            return None
        if quoted.startswith("'") and quoted.endswith("'"):
            try:
                inner = ast.literal_eval(quoted)
            except (SyntaxError, ValueError):
                return quoted
            if isinstance(inner, str):
                return repr(inner)
        return quoted
    if tail[0] == "'":
        try:
            value, consumed = _parse_one_literal(tail)
        except ValueError:
            return None
        rest = tail[consumed:].lstrip()
        if rest.startswith("}") or rest.startswith(", '"):
            inner = tail[1:consumed - 1]
            return inner
        return repr(value)
    end = tail.find(", '")
    if end == -1:
        end = len(tail.rstrip("}"))
    token = tail[:end].strip()
    if token.endswith("'") and not token.startswith("'"):
        token = token[:-1]
    return token


def _parse_name(locals_str: str) -> str | None:
    raw = _extract_local_repr(locals_str, "name")
    if raw is None:
        return None
    return _parse_name_repr(raw)


def _observation_qualifies(
    line: int,
    event: str,
    state: dict[str, str],
) -> bool:
    if event != "line":
        return False
    if line == OBS_LINE_FIRST_LOOP:
        return "name" in state and "value_repr" in state
    if line == OBS_LINE_SECOND_LOOP:
        return "name" in state and "value_repr" in state
    if line == OBS_LINE_CTX_NONE:
        return "data_repr" in state
    return False


def _value_is_missing(locals_str: str) -> bool:
    raw = _extract_local_repr(locals_str, "value")
    return raw == "missing"


def _data_is_empty_dict(locals_str: str) -> bool:
    raw = _extract_local_repr(locals_str, "data")
    if raw is None:
        return False
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return False
    return parsed == {}


def _evaluate_predicate(kind: str, locals_str: str) -> bool:
    name = _parse_name(locals_str)
    if kind == "data_empty":
        return _data_is_empty_dict(locals_str)
    if name is None:
        return False
    if kind == "len_gt_8":
        return len(name) > 8
    if kind == "len_lt_6":
        return len(name) < 6
    if kind == "eq_context":
        return name == "context"
    if kind == "starts_l":
        return name.startswith("l_")
    if kind == "is_missing":
        return _value_is_missing(locals_str)
    raise ValueError(f"unknown predicate kind: {kind}")


def _parse_name_repr(name_repr: str) -> str | None:
    try:
        parsed = ast.literal_eval(name_repr)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, str):
        return None
    return parsed


def _evaluate_predicate_on_state(kind: str, state: dict[str, str]) -> bool:
    if kind == "data_empty":
        data_repr = state.get("data_repr")
        if data_repr is None:
            return False
        try:
            parsed = ast.literal_eval(data_repr)
        except (SyntaxError, ValueError):
            return False
        return parsed == {}
    name = state.get("name")
    if name is None:
        return False
    if kind == "len_gt_8":
        return len(name) > 8
    if kind == "len_lt_6":
        return len(name) < 6
    if kind == "eq_context":
        return name == "context"
    if kind == "starts_l":
        return name.startswith("l_")
    if kind == "is_missing":
        return state.get("value_repr") == "missing"
    raise ValueError(f"unknown predicate kind: {kind}")


def _merge_changed_locals(state: dict[str, str], locals_str: str | None) -> None:
    if locals_str is None:
        return
    name_repr = _extract_local_repr(locals_str, "name")
    if name_repr is not None:
        parsed_name = _parse_name_repr(name_repr)
        if parsed_name is not None:
            state["name"] = parsed_name
    value_repr = _extract_local_repr(locals_str, "value")
    if value_repr is not None:
        state["value_repr"] = value_repr
    data_repr = _extract_local_repr(locals_str, "data")
    if data_repr is not None:
        state["data_repr"] = data_repr


def _parse_trace_events(trace_log: Path) -> list[tuple[int, str, str | None]]:
    if not trace_log.is_file():
        raise SystemExit(f"ERROR: trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_log}")

    events: list[tuple[int, str, str | None]] = []
    for raw_line in text.splitlines():
        if TARGET_FUNC not in raw_line:
            continue
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        rel_file = _repo_relative_path(match.group("file"))
        if rel_file != TARGET_REL_FILE:
            continue
        locals_idx = raw_line.find(" locals=")
        locals_str = raw_line[locals_idx + len(" locals=") :] if locals_idx != -1 else None
        events.append(
            (
                int(match.group("line")),
                match.group("event"),
                locals_str,
            )
        )

    if not events:
        raise SystemExit(
            f"ERROR: no trace events for {TARGET_FUNC} in {trace_log}"
        )

    return events


def _build_invariant_report(
    events: list[tuple[int, str, str | None]],
) -> list[dict[str, object]]:
    stats: dict[str, dict[str, int]] = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in PREDICATES
    }
    frame_state: dict[str, str] = {}

    for line, event, locals_str in events:
        if event == "call":
            frame_state = {}
            continue
        _merge_changed_locals(frame_state, locals_str)
        for predicate, (obs_line, kind) in PREDICATES.items():
            if line != obs_line:
                continue
            if not _observation_qualifies(line, event, frame_state):
                continue
            stats[predicate]["observations"] += 1
            if not _evaluate_predicate_on_state(kind, frame_state):
                stats[predicate]["violations"] += 1

    report: list[dict[str, object]] = []
    for predicate in sorted(PREDICATES):
        observations = stats[predicate]["observations"]
        violations = stats[predicate]["violations"]
        held_always = violations == 0 and observations > 0
        report.append(
            {
                "predicate": predicate,
                "held_always": held_always,
                "observations": observations,
                "violations": violations,
            }
        )

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)

    line_events = [event for event in events if event[1] == "line"]
    distinct_lines = {line for line, event, _loc in events if event == "line"}
    line_counts: dict[int, int] = {}
    for line, event, _loc in events:
        if event == "line":
            line_counts[line] = line_counts.get(line, 0) + 1

    if len(line_events) < 60:
        raise SystemExit(
            f"ERROR: expected at least 60 line events, found {len(line_events)}"
        )
    if len(distinct_lines) < 8:
        raise SystemExit(
            f"ERROR: expected at least 8 distinct executed lines, found {len(distinct_lines)}"
        )
    if not any(count >= 20 for count in line_counts.values()):
        raise SystemExit("ERROR: expected at least one line executed 20+ times")

    invariant_report = _build_invariant_report(events)

    if all(entry["observations"] == 0 for entry in invariant_report):
        raise SystemExit("ERROR: no predicate observations recorded")

    oracle_answer = {"invariant_report": invariant_report}
    template_answer = {
        "invariant_report": [
            {
                "held_always": "bool",
                "observations": "int",
                "predicate": "str",
                "violations": "int",
            }
        ]
    }

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
