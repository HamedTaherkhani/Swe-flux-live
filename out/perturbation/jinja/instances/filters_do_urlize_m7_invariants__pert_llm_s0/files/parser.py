#!/usr/bin/env python3
"""Parse trace logs for do_urlize runtime invariant violation accounting."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

TARGET_FILE = "src/jinja2/filters.py"
TARGET_FUNC = "jinja2.filters.do_urlize"
URI_SCHEME_RE = re.compile(r"^([\w.+-]{2,}:(/){0,2})$")

PREDICATES: list[dict[str, Any]] = [
    {
        "predicate": "isinstance(rel_parts, set)",
        "line": 795,
    },
    {
        "predicate": "len(value) > 0",
        "line": 795,
    },
    {
        "predicate": 'nofollow is False or "nofollow" in rel_parts',
        "line": 795,
    },
    {
        "predicate": "target is not None",
        "line": 795,
    },
    {
        "predicate": "scheme in tuple(extra_schemes)",
        "line": 804,
    },
    {
        "predicate": (
            're.compile(r"^([\\w.+-]{2,}:(/){0,2})$").fullmatch(scheme) is not None'
        ),
        "line": 804,
    },
    {
        "predicate": "isinstance(rv, str)",
        "line": 816,
    },
]

EVENT_RE = re.compile(
    r"^(?P<path>.+):(?P<lineno>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
    r"(?:\s+retval=(?P<retval>.*?))?(?:\s+exc=(?P<exc>.*?))?\s+locals=(?P<locals>\{.*\})$"
)


def _parse_locals(raw: str) -> dict[str, str]:
    try:
        parsed = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Could not parse locals dict: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected locals dict, got {type(parsed)!r}")
    return {str(k): str(v) for k, v in parsed.items()}


def _parse_trace_line(line: str) -> dict[str, str] | None:
    body = line.split(" ", 1)[-1] if " " in line else line
    match = EVENT_RE.match(body.strip())
    if not match:
        return None
    groups = match.groupdict()
    return {
        "path": groups["path"].replace("\\", "/"),
        "lineno": groups["lineno"],
        "func": groups["func"],
        "event": groups["event"],
        "locals": groups["locals"] or "{}",
    }


def _in_target_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(TARGET_FILE) or TARGET_FILE in normalized


def _coerce_local(name: str, raw: str) -> Any:
    if raw == "None":
        return None
    if raw == "True":
        return True
    if raw == "False":
        return False
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        if name in {"value", "rv"} and "..." in raw:
            return "__trace_truncated_non_empty__"
        raise ValueError(
            f"Could not coerce local {name!r} from trace repr {raw!r}"
        ) from None


def _get_binding(merged: dict[str, str], name: str) -> Any:
    if name not in merged:
        return None
    return _coerce_local(name, merged[name])


def _bindings_for_predicate(predicate: str, merged: dict[str, str]) -> dict[str, Any]:
    needed = {
        "isinstance(rel_parts, set)": ("rel_parts",),
        "len(value) > 0": ("value",),
        'nofollow is False or "nofollow" in rel_parts': ("nofollow", "rel_parts"),
        "target is not None": ("target",),
        "scheme in tuple(extra_schemes)": ("scheme", "extra_schemes"),
        (
            're.compile(r"^([\\w.+-]{2,}:(/){0,2})$").fullmatch(scheme) is not None'
        ): ("scheme",),
        "isinstance(rv, str)": ("rv",),
    }[predicate]
    return {name: _get_binding(merged, name) for name in needed}


def _eval_predicate(predicate: str, bindings: dict[str, Any]) -> bool:
    rel_parts = bindings.get("rel_parts")
    value = bindings.get("value")
    nofollow = bindings.get("nofollow")
    target = bindings.get("target")
    scheme = bindings.get("scheme")
    extra_schemes = bindings.get("extra_schemes")
    rv = bindings.get("rv")

    if predicate == "isinstance(rel_parts, set)":
        return isinstance(rel_parts, set)
    if predicate == "len(value) > 0":
        return value == "__trace_truncated_non_empty__" or (
            isinstance(value, str) and len(value) > 0
        )
    if predicate == 'nofollow is False or "nofollow" in rel_parts':
        return nofollow is False or (
            isinstance(rel_parts, set) and "nofollow" in rel_parts
        )
    if predicate == "target is not None":
        return target is not None
    if predicate == "scheme in tuple(extra_schemes)":
        if extra_schemes is None:
            return False
        return scheme in tuple(extra_schemes)
    if predicate == (
        're.compile(r"^([\\w.+-]{2,}:(/){0,2})$").fullmatch(scheme) is not None'
    ):
        return isinstance(scheme, str) and URI_SCHEME_RE.fullmatch(scheme) is not None
    if predicate == "isinstance(rv, str)":
        return isinstance(rv, str)
    raise ValueError(f"Unknown predicate: {predicate}")


def harvest_invariant_report(trace_log: Path) -> list[dict[str, Any]]:
    if not trace_log.is_file():
        raise SystemExit(f"Trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"Trace log is empty: {trace_log}")

    stats = {
        item["predicate"]: {"observations": 0, "violations": 0}
        for item in PREDICATES
    }
    predicates_by_line = {}
    for item in PREDICATES:
        predicates_by_line.setdefault(item["line"], []).append(item["predicate"])

    target_events = 0
    in_invocation = False
    merged: dict[str, str] = {}

    for raw_line in text.splitlines():
        parsed = _parse_trace_line(raw_line)
        if parsed is None:
            continue
        if parsed["func"] != TARGET_FUNC or not _in_target_file(parsed["path"]):
            continue

        target_events += 1
        event = parsed["event"]
        lineno = int(parsed["lineno"])

        if event == "call":
            in_invocation = True
            merged = _parse_locals(parsed["locals"])
            continue

        if not in_invocation:
            continue

        if event in {"return", "exception"}:
            in_invocation = False
            continue

        if event != "line":
            continue

        merged.update(_parse_locals(parsed["locals"]))

        for predicate in predicates_by_line.get(lineno, []):
            bindings = _bindings_for_predicate(predicate, merged)
            try:
                held = _eval_predicate(predicate, bindings)
            except ValueError as exc:
                raise SystemExit(
                    f"Predicate {predicate!r} at line {lineno} failed to evaluate: {exc}"
                ) from exc
            stats[predicate]["observations"] += 1
            if not held:
                stats[predicate]["violations"] += 1

    if target_events == 0:
        raise SystemExit(
            f"No trace events found for {TARGET_FUNC} in {TARGET_FILE}"
        )

    report = []
    for item in sorted(PREDICATES, key=lambda entry: entry["predicate"]):
        predicate = item["predicate"]
        observations = stats[predicate]["observations"]
        violations = stats[predicate]["violations"]
        report.append(
            {
                "predicate": predicate,
                "held_always": violations == 0 and observations > 0,
                "observations": observations,
                "violations": violations,
            }
        )

    return report


def build_question() -> str:
    predicate_lines = "\n".join(
        f'- "{item["predicate"]}" observed at line {item["line"]} (`event=line`)'
        for item in sorted(PREDICATES, key=lambda entry: entry["predicate"])
    )
    return (
        "Consider every test method in "
        "`jinja_qa/filters_do_urlize_m7_invariants/files/testcase.py::"
        "TestDoUrlizeInvariantReport`. The answer aggregates behavior across "
        "**all** `test_*` methods in that class, in the chronological order "
        "pytest collects and runs them (definition order in the file).\n\n"
        "Those tests call `do_urlize` **directly** from `jinja2.filters` "
        "(imported as `jinja2.filters.do_urlize`).\n\n"
        "Target function: `jinja2.filters.do_urlize` (the function whose `def` "
        f"begins at line 742 of `{TARGET_FILE}`).\n\n"
        "An **invocation** is one `call` trace event for "
        f"`{TARGET_FUNC}` during the test run, numbered chronologically "
        "starting at 1 in the order those `call` events appear. Within one "
        "invocation, maintain a map of local variable bindings by scanning "
        "every `line` event for that invocation from its `call` through its "
        "matching `return` or `exception` event. The invocation's `call` "
        "event seeds initial bindings from its `locals={...}` dictionary; "
        "each subsequent `line` event's `locals={...}` dictionary supplies "
        "bindings that overwrite earlier bindings for the same name; only keys "
        "present in those per-event dictionaries participate.\n\n"
        "Binding values in the trace are Python `repr()` strings. Reconstruct "
        "each local by applying `ast.literal_eval` to its repr when possible; "
        "`None`, `True`, and `False` appear as those tokens. Strings use "
        "Python's normal `repr` quoting rules (for example, a string holding "
        "`alpha` is `'alpha'`). Sets and tuples appear as their `repr` forms "
        "such as `{'a', 'b'}` or `('tel:', 'ftp:')`. When a string local's "
        "repr ends with an ellipsis suffix (`...`) immediately before its "
        "closing quote delimiter, treat that binding as a non-empty string "
        "whose exact contents are unavailable (for example, `'alpha beta "
        "...'` denotes a non-empty `value`).\n\n"
        "For each candidate predicate below, evaluate it on the reconstructed "
        "locals immediately **after** the stated physical line executes "
        "(equivalently: on the merged binding map right after processing that "
        "line's `line` event). Count one **observation** per execution of "
        "that line across all invocations and all test methods. A predicate "
        "**violates** on an observation when it evaluates to `False`. "
        "`held_always` is `true` only when `violations == 0` and "
        "`observations > 0`. If the observation line never executes during "
        "the run, report `observations: 0`, `violations: 0`, "
        "`held_always: false`.\n\n"
        "Candidate predicates (verbatim strings) and their observation points:\n"
        f"{predicate_lines}\n\n"
        "For the URI-scheme predicate, use exactly this compiled pattern: "
        '`re.compile(r"^([\\w.+-]{2,}:(/){0,2})$")` applied to the local '
        "`scheme`.\n\n"
        "Line numbers are absolute, 1-based, in `src/jinja2/filters.py` as it "
        "exists in the repository. For multi-line statements, a `line` event "
        "fires on the line where that statement begins. The `def` line, "
        "decorator lines, and docstring lines are never observation points.\n\n"
        "Return JSON with exactly one top-level key `invariant_report`: a "
        "list of objects, each with keys `predicate` (string), `held_always` "
        "(boolean), `observations` (non-negative integer), and `violations` "
        "(non-negative integer). Sort the list by `predicate` ascending using "
        "Unicode code-point order; when predicates tie (they cannot), break "
        "ties by `observations` ascending."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    invariant_report = harvest_invariant_report(args.trace_log)
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
        "question": build_question(),
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(oracle_answer, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
