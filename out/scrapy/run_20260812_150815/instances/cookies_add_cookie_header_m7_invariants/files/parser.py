from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Callable


TARGET_FILE = "scrapy/http/cookies.py"
TARGET_FUNC = "scrapy.http.cookies.CookieJar.add_cookie_header"
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

Predicate = tuple[str, int, Callable[[dict[str, object]], bool]]
PREDICATES: tuple[Predicate, ...] = (
    ("bool(attrs)", 67, lambda values: bool(values["attrs"])),
    ("host == req_host", 63, lambda values: values["host"] == values["req_host"]),
    (
        "host.startswith('.')",
        63,
        lambda values: str(values["host"]).startswith("."),
    ),
    ("len(attrs) >= 2", 68, lambda values: len(values["attrs"]) >= 2),
    (
        "len(host) % 2 == len(req_host) % 2",
        63,
        lambda values: len(values["host"]) % 2 == len(values["req_host"]) % 2,
    ),
    ("req_host is None", 52, lambda values: values["req_host"] is None),
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def decode_changed_locals(raw_line: str) -> dict[str, object]:
    marker = " locals="
    if marker not in raw_line:
        fail(f"target event has no locals payload: {raw_line}")
    payload = raw_line.rsplit(marker, 1)[1]
    try:
        encoded = ast.literal_eval(payload)
    except (SyntaxError, ValueError) as exc:
        fail(f"cannot parse locals payload: {exc}")
    if not isinstance(encoded, dict):
        fail("locals payload is not a dictionary")

    decoded: dict[str, object] = {}
    for name, representation in encoded.items():
        if not isinstance(name, str) or not isinstance(representation, str):
            fail("locals payload has an unexpected key or value type")
        if name not in {"attrs", "host", "req_host"}:
            continue
        try:
            decoded[name] = ast.literal_eval(representation)
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot decode local {name!r}: {exc}")
    return decoded


def parse_trace(trace_path: Path) -> list[tuple[str, int, dict[str, object]]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events: list[tuple[str, int, dict[str, object]]] = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        events.append(
            (
                match.group("event"),
                int(match.group("line")),
                decode_changed_locals(raw_line),
            )
        )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event == "call" for event, _, _ in events):
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    return events


def build_answer(
    events: list[tuple[str, int, dict[str, object]]],
) -> dict[str, object]:
    counts = {
        predicate: {"observations": 0, "violations": 0}
        for predicate, _, _ in PREDICATES
    }
    current: dict[str, object] | None = None
    invocations = 0

    for event, line, changed in events:
        if event == "call":
            invocations += 1
            current = {}
        if current is None:
            continue
        current.update(changed)
        if event == "line":
            for predicate, observation_line, evaluator in PREDICATES:
                if line != observation_line:
                    continue
                try:
                    held = evaluator(current)
                except (KeyError, TypeError) as exc:
                    fail(
                        f"cannot evaluate {predicate!r} at line {line} "
                        f"in invocation {invocations}: {exc}"
                    )
                counts[predicate]["observations"] += 1
                if not held:
                    counts[predicate]["violations"] += 1
        if event == "return":
            current = None

    if invocations == 0:
        fail(f"trace contains zero invocations for {TARGET_FUNC}")

    report = []
    for predicate in sorted(counts):
        observations = counts[predicate]["observations"]
        violations = counts[predicate]["violations"]
        report.append(
            {
                "held_always": observations > 0 and violations == 0,
                "observations": observations,
                "predicate": predicate,
                "violations": violations,
            }
        )
    return {"invariant_report": report}


def question_text() -> str:
    methods = ", ".join(
        f"`{name}`"
        for name in (
            "test_deep_domain_cookie_mix",
            "test_sparse_suffix_domains",
            "test_secure_request_dense_jar",
            "test_existing_header_blocks_append",
            "test_ipv4_host_candidates",
            "test_single_label_local_candidates",
            "test_empty_jar_long_hostname",
            "test_frequent_expiry_sweep",
            "test_two_label_boundary",
            "test_odd_label_lengths",
            "test_shallow_domain_many_cookies",
            "test_preset_header_with_expiry",
        )
    )
    candidates = "; ".join(
        f"`{predicate}` at line {line}" for predicate, line, _ in PREDICATES
    )
    return (
        "Run every pytest method in "
        "`scrapy_qa/cookies_add_cookie_header_m7_invariants/files/"
        "testcase.py::CookieHeaderInvariantTest`: "
        f"{methods}. The pytest id for each is the class node id followed by "
        "`::<method-name>`; use pytest's normal collected order. Aggregate over "
        "ALL listed test methods and all direct invocations of "
        "`scrapy.http.cookies.CookieJar.add_cookie_header` in "
        "`scrapy/http/cookies.py`. An invocation is one entry into that exact "
        "function, numbered 1-based in chronological order across the complete "
        "run; invocation numbers are not emitted. Evaluate these six candidate "
        f"predicates verbatim at their respective observation lines: {candidates}. "
        "Each line number is an absolute, 1-based physical line number in the "
        "named repository file as it exists for this run. An observation occurs "
        "immediately before the statement beginning on that line executes in the "
        "target function's own frame, after all effects of the previously "
        "executed line; only an actually executed observation line counts. For a "
        "multi-line statement or expression, the observation belongs to the "
        "physical line where that statement or expression begins. The `def` line, "
        "decorators, docstrings, calls and frames of callees, and return or "
        "exception events are not observations. A loop-header observation would "
        "include its final exhaustion check, but these candidates do not observe "
        "a loop header. Evaluate a predicate using the ordinary Python semantics "
        "of the displayed expression and the target frame's local values at that "
        "instant. One execution of its stated line contributes exactly one "
        "observation to that predicate, including repeated executions in a loop; "
        "sum observations across every invocation and listed method. A violation "
        "is an observation where the expression evaluates to false. "
        "`held_always` is true exactly when `violations == 0` and `observations > "
        "0`. If a predicate's line is never reached, report `observations` as 0, "
        "`violations` as 0, and `held_always` as false. Return exactly one JSON "
        "object with the single key `invariant_report`, whose value is a JSON "
        "array containing one object for each stated candidate, with no "
        "deduplication and no additional entries. Every object has exactly these "
        "four keys: `predicate` is a JSON string containing the predicate exactly "
        "as displayed above, without Markdown backticks or added `repr()` quotes; "
        "`held_always` is a JSON boolean; and `observations` and `violations` are "
        "JSON integers. No runtime local value, function name, file name, line "
        "number, invocation number, null placeholder, Python `repr`, or extra key "
        "is serialized in the answer. Sort the array by the `predicate` string in "
        "ascending Unicode code-point order. Exact duplicate predicate strings "
        "would retain their statement order as the tie-break, though the six "
        "stated candidates are distinct."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = build_answer(parse_trace(Path(args.trace_log)))
    payload = {
        "question_kind": "M7_Invariants",
        "question": question_text(),
        "template_answer": {
            "invariant_report": [
                {
                    "held_always": "bool",
                    "observations": "int",
                    "predicate": "str",
                    "violations": "int",
                }
            ]
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
