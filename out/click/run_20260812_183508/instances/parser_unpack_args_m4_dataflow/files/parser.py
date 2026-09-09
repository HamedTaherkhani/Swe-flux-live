from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/parser.py"
TARGET_FUNC = "click.parser._unpack_args"
FETCH_FUNC = "click.parser._unpack_args.<locals>._fetch"
COMPREHENSION_FUNC = "click.parser._unpack_args.<locals>.<listcomp>"
TRACKED_VARIABLES = {
    "_fetch",
    "args",
    "nargs",
    "nargs_spec",
    "rv",
    "spos",
    "x",
}

# Name loads evaluated by each line event in the outer function. Repeated
# entries represent repeated evaluations of the same name on one execution.
OUTER_USES = {
    63: ("args",),
    64: ("nargs_spec",),
    77: ("nargs_spec",),
    78: ("spos",),
    79: ("nargs_spec",),
    81: ("nargs_spec",),
    83: ("nargs",),
    84: ("rv", "_fetch", "args"),
    85: ("nargs",),
    86: ("nargs",),
    90: ("spos",),
    91: ("x",),
    93: ("rv", "x"),
    94: ("nargs",),
    95: ("spos",),
    98: ("rv",),
    99: ("rv",),
    103: ("spos",),
    104: ("args", "rv", "spos"),
    106: ("rv", "spos", "rv", "spos"),
    108: ("rv", "args"),
}

# Successful executions of these source lines bind a tracked bare name.
OUTER_DEFS = {
    63: ("args",),
    64: ("nargs_spec",),
    65: ("rv",),
    66: ("spos",),
    68: ("_fetch",),
    79: ("nargs",),
    81: ("nargs",),
    86: ("x",),
    98: ("spos",),
    105: ("args",),
}

QUESTION = """Run every pytest test method in the class `TestGeneratedArgumentLayouts` in `click_qa/parser_unpack_args_m4_dataflow/files/testcase.py`, equivalently every collected pytest id below `click_qa/parser_unpack_args_m4_dataflow/files/testcase.py::TestGeneratedArgumentLayouts`. Pytest identifies and runs these methods by their full pytest ids in its normal ascending name order. Aggregate the requested counts over ALL test methods in that class, not over only one method. During that complete run, consider every invocation of the target function `click.parser._unpack_args` in the repository file `src/click/parser.py`.

Report all dynamically observed def-use pairs for exactly these seven tracked variables in `_unpack_args`: `_fetch`, `args`, `nargs`, `nargs_spec`, `rv`, `spos`, and `x`. A definition is a successful runtime binding of a tracked bare local name by a parameter binding, assignment, annotated assignment, or nested `def`. The two parameters `args` and `nargs_spec` are each defined at the target function's `def` line when an invocation begins. A nested `def` defines its function-name variable when that statement executes. Assignment to a subscript or attribute and mutation through a method such as `rv.append(...)` use the base variable but do not define it. A plain assignment's right-hand side uses occur before its new definition takes effect. If an augmented assignment to a tracked name occurred, it would first use the reaching definition and then define that name at the augmented-assignment line; none occurs here. A tracked `for`-loop target would be defined once for each successfully obtained item before that iteration's body, while names read to obtain the iterable are uses; no tracked variable is a loop target here.

A use is one runtime evaluation of a tracked name in Python `Load` context, reached by that variable's most recent definition in the same `_unpack_args` invocation. Count repeated evaluations separately even when they have the same source line: for example, evaluating a hypothetical expression `q + q` once would produce two observations for the same pair. Condition tests count every time they are evaluated, including the final false test of a loop. Calls use the name holding the callable, and using a tracked object as a method-call receiver, subscript base, or iterable counts as a use. Merely displaying a local in debugging output is not a use.

The syntactically nested `_fetch` function and list comprehension on the annotated assignment to `x` are part of this data-flow accounting only where they evaluate one of the seven tracked variables from `_unpack_args`. Thus each evaluation of the comprehension element expression counts its loads of outer `_fetch` and outer `args` at the source line on which that comprehension expression begins, and each execution of `_fetch`'s `spos` condition counts a use of outer `spos`. The comprehension-local `_` and `_fetch`'s parameter `c` are not tracked, nor are any other nested-scope locals. The comprehension's iterable expression is evaluated once in the outer frame under the ordinary rules above. An iteration of the `while nargs_spec` loop means one execution of its body after a true evaluation of that condition; uses in the condition and body are counted whenever they actually execute.

An invocation means one Python call of `click.parser._unpack_args` during the complete class run. Number invocations from 1 in chronological call order if instrumentation needs to distinguish their reaching definitions, but do not include invocation numbers in the answer. A definition never reaches across invocations. One observation is one executed use event reached by one definition, so a use in a loop body or comprehension contributes once per actual evaluation. `count` is the total number of observations of that exact `(variable, def_line, use_line)` triple summed across all invocations in all test methods in the class.

Both `def_line` and `use_line` are absolute 1-based source line numbers in `src/click/parser.py` as checked out. For a multi-line statement or expression, use the line where the relevant definition target or name expression begins; the function parameters are defined at the line where the multi-line `def` statement begins. Decorator and docstring lines are not definitions or uses unless they independently evaluate a tracked name under the rules above. Lines in the nested helper or comprehension still use their absolute line numbers in that same file.

Return exactly `{"observed_def_use_pairs": [{"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}]}`. The value is a JSON array containing one object for every observed triple and no object for a never-observed triple. Each object has the tracked variable name as a direct JSON string (not Python `repr()`), and three JSON integers. Sort objects ascending by `variable` using Python string ordering, then by integer `def_line`, then by integer `use_line`. Emit each triple exactly once; `count` carries all multiplicity, so there are no duplicate rows. The array is non-empty, and no empty string, JSON null, or omitted field represents a value."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def parse_trace(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    current_defs: dict[str, int] | None = None
    in_comprehension = 0
    target_events = 0
    target_calls = 0
    target_returns = 0
    observations: Counter[tuple[str, int, int]] = Counter()

    def observe(variable: str, use_line: int) -> None:
        if current_defs is None:
            fail(f"use of {variable} at line {use_line} outside a target invocation")
        if variable not in current_defs:
            fail(f"use of {variable} at line {use_line} has no reaching definition")
        observations[(variable, current_defs[variable], use_line)] += 1

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue

        filename = match.group("file").replace("\\", "/")
        function = match.group("func")
        event = match.group("event")
        line = int(match.group("line"))
        if not filename.endswith(TARGET_FILE_SUFFIX):
            continue
        if function not in {TARGET_FUNC, FETCH_FUNC, COMPREHENSION_FUNC}:
            continue

        if function == TARGET_FUNC:
            target_events += 1
            if event == "call":
                if current_defs is not None:
                    fail("overlapping target invocations are not supported")
                current_defs = {"args": 51, "nargs_spec": 51}
                in_comprehension = 0
                target_calls += 1
            elif event == "line":
                if current_defs is None:
                    fail(f"target line event at {line} occurred without an invocation")
                for variable in OUTER_USES.get(line, ()):
                    observe(variable, line)
                for variable in OUTER_DEFS.get(line, ()):
                    current_defs[variable] = line
            elif event == "return":
                if current_defs is None:
                    fail("target return occurred without an invocation")
                if in_comprehension:
                    fail("target returned while a comprehension was active")
                current_defs = None
                target_returns += 1
            continue

        if current_defs is None:
            fail(f"nested event for {function} occurred outside a target invocation")

        if function == COMPREHENSION_FUNC:
            if event == "call":
                in_comprehension += 1
            elif event == "return":
                if in_comprehension <= 0:
                    fail("comprehension return occurred without a matching call")
                in_comprehension -= 1
            continue

        if function == FETCH_FUNC:
            if event == "call" and in_comprehension:
                observe("_fetch", 86)
                observe("args", 86)
            elif event == "line" and line == 70:
                observe("spos", 70)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if target_calls != target_returns:
        fail(
            f"target call/return mismatch: {target_calls} calls, "
            f"{target_returns} returns"
        )
    if current_defs is not None:
        fail("trace ended during an active target invocation")
    if in_comprehension:
        fail("trace ended during an active comprehension")
    if not observations:
        fail("trace contains no observed def-use pairs")

    rows = [
        {
            "variable": variable,
            "def_line": def_line,
            "use_line": use_line,
            "count": count,
        }
        for (variable, def_line, use_line), count in sorted(observations.items())
    ]
    return {"observed_def_use_pairs": rows}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {
                    "count": "int",
                    "def_line": "int",
                    "use_line": "int",
                    "variable": "str",
                }
            ]
        },
        "oracle_answer": parse_trace(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote oracle to {arguments.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
