from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scrapy/commands/check.py"
TARGET_FUNC = "scrapy.commands.check.Command.run"

PREDICATES = {
    "bool(args) and opts.list": 91,
    "(sum(map(ord, spidername)) + len(args)) % 4 != 0": 95,
    "sum(map(ord, spidername)) % 251 != len(args) % 251": 95,
    "len(tested_methods) > len(spidername) % 5": 99,
    "len(method) > len(spidername) // 3": 101,
    "len(tested_methods) >= len(args)": 103,
}

TEST_METHODS = [
    "test_seeded_listing_explicit_forward",
    "test_seeded_listing_loader_reverse",
    "test_seeded_execution_explicit_reverse",
    "test_seeded_execution_loader_interleaved",
    "test_listing_wide_names",
    "test_execution_wide_names",
    "test_listing_alternate_order",
    "test_execution_alternate_order",
    "test_listing_dense_contracts",
    "test_execution_dense_contracts",
    "test_listing_final_mix",
    "test_execution_final_mix",
]

QUESTION = """Run every test method in `scrapy_qa/check_run_m7_invariants/files/testcase.py::CheckRunInvariantTests` and aggregate observations across the whole class. The contributing pytest IDs are the class path followed by each of these method names: test_seeded_listing_explicit_forward, test_seeded_listing_loader_reverse, test_seeded_execution_explicit_reverse, test_seeded_execution_loader_interleaved, test_listing_wide_names, test_execution_wide_names, test_listing_alternate_order, test_execution_alternate_order, test_listing_dense_contracts, test_execution_dense_contracts, test_listing_final_mix, and test_execution_final_mix. Collection order does not affect the requested totals.

For the exact target frame `scrapy.commands.check.Command.run` in `scrapy/commands/check.py`, evaluate the following six candidate predicates verbatim. Each predicate has its own observation point, shown after it:

- `bool(args) and opts.list` — a `line` event at line 91.
- `(sum(map(ord, spidername)) + len(args)) % 4 != 0` — a `line` event at line 95.
- `sum(map(ord, spidername)) % 251 != len(args) % 251` — a `line` event at line 95.
- `len(tested_methods) > len(spidername) % 5` — a `line` event at line 99.
- `len(method) > len(spidername) // 3` — a `line` event at line 101.
- `len(tested_methods) >= len(args)` — a `line` event at line 103.

Line numbers are absolute, 1-based source line numbers in the named repository file. A `line` event is counted immediately before Python executes the statement or expression beginning on that line, using the local values visible in that frame at that moment. Multi-line statements are associated with the line on which the executed statement or expression begins. Count only events whose frame qualname is exactly `scrapy.commands.check.Command.run`: exclude its nested `start` function, generator/comprehension frames, callees, and all other frames. `call`, `return`, and `exception` events do not count. The function's `def` line, comments, and non-executed lines do not create observations.

Use ordinary Python expression semantics for `bool`, `len`, `sum`, `map`, `ord`, integer arithmetic, comparisons, and attribute access. Evaluate a predicate once for every occurrence of its stated observation event, including repeated loop visits and repeated calls, and sum across all listed test methods. An invocation means one call of the exact target function; if invocation ordering is needed to reproduce the run, invocations are 1-based in chronological execution order, though the requested counts are order-independent.

Return exactly `{"invariant_report": [...]}`. Include one object for each candidate, with exactly these keys: `predicate` (JSON string, copied verbatim from the candidate), `observations` (JSON integer count of evaluations), `violations` (JSON integer count whose evaluation was false), and `held_always` (JSON boolean equal to `violations == 0` only when `observations > 0`). If an observation point is never reached, report `observations: 0`, `violations: 0`, and `held_always: false`. Preserve duplicate observations; do not deduplicate events. Sort report objects by the full `predicate` string in ascending Unicode code-point order. Candidate strings are unique, so no tie can occur; if identical predicate strings were present, retain their question order as the tie-break. JSON booleans are serialized as `true` or `false`, and integers are JSON numbers, not strings. No `repr()` or `str()` conversion is applied to counts or booleans."""


LINE_RE = re.compile(
    r"(?P<file>\S*scrapy/commands/check\.py):(?P<line>\d+) "
    r"scrapy\.commands\.check\.Command\.run event=(?P<event>\w+)"
    r"(?: .*?)? locals=(?P<locals>\{.*\})$"
)


def _namespace_flags(value: str) -> tuple[bool, bool]:
    match = re.fullmatch(r"Namespace\(list=(True|False), verbose=(True|False)\)", value)
    if not match:
        raise ValueError(f"cannot parse opts value: {value!r}")
    return match.group(1) == "True", match.group(2) == "True"


def _evaluate(predicate: str, state: dict[str, str]) -> bool:
    def literal(name: str):
        if name not in state:
            raise ValueError(f"missing local {name!r} for predicate {predicate!r}")
        return ast.literal_eval(state[name])

    if predicate == "bool(args) and opts.list":
        args = literal("args")
        list_mode, _ = _namespace_flags(state["opts"])
        return bool(args) and list_mode
    if predicate == "(sum(map(ord, spidername)) + len(args)) % 4 != 0":
        spidername = literal("spidername")
        args = literal("args")
        return (sum(map(ord, spidername)) + len(args)) % 4 != 0
    if predicate == "sum(map(ord, spidername)) % 251 != len(args) % 251":
        spidername = literal("spidername")
        args = literal("args")
        return sum(map(ord, spidername)) % 251 != len(args) % 251
    if predicate == "len(tested_methods) > len(spidername) % 5":
        tested_methods = literal("tested_methods")
        spidername = literal("spidername")
        return len(tested_methods) > len(spidername) % 5
    if predicate == "len(method) > len(spidername) // 3":
        method = literal("method")
        spidername = literal("spidername")
        return len(method) > len(spidername) // 3
    if predicate == "len(tested_methods) >= len(args)":
        tested_methods = literal("tested_methods")
        args = literal("args")
        return len(tested_methods) >= len(args)
    raise AssertionError(f"unknown predicate: {predicate}")


def build_answer(trace_path: Path) -> dict:
    if not trace_path.is_file():
        raise FileNotFoundError(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"trace log is empty: {trace_path}")

    counts = {
        predicate: {"observations": 0, "violations": 0}
        for predicate in PREDICATES
    }
    state: dict[str, str] = {}
    target_events = 0

    for raw_line in text.splitlines():
        match = LINE_RE.search(raw_line)
        if not match:
            continue
        target_events += 1
        event = match.group("event")
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"malformed locals on trace line: {raw_line}") from exc
        if not isinstance(changed, dict):
            raise ValueError(f"locals are not a dictionary on trace line: {raw_line}")

        if event == "call":
            state = {}
        state.update(changed)

        if event != "line":
            if event == "return":
                state = {}
            continue

        lineno = int(match.group("line"))
        for predicate, observation_line in PREDICATES.items():
            if lineno != observation_line:
                continue
            counts[predicate]["observations"] += 1
            if not _evaluate(predicate, state):
                counts[predicate]["violations"] += 1

    if target_events == 0:
        raise ValueError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    report = []
    for predicate in sorted(PREDICATES):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        answer = build_answer(Path(args.trace_log))
        payload = {
            "question_kind": "M7_Invariants",
            "question": QUESTION,
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
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
