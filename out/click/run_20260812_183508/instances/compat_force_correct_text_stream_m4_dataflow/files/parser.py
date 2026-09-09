from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys


TARGET_FILE_SUFFIX = "/src/click/_compat.py"
TARGET_FUNC = "click._compat._force_correct_text_stream"
TARGET_NAME = "_force_correct_text_stream"
TRACKED_VARIABLES = {
    "binary_reader",
    "encoding",
    "errors",
    "find_binary",
    "force_readable",
    "force_writable",
    "is_binary",
    "possible_binary_reader",
    "text_stream",
}

QUESTION = """Run every pytest test method in the class `TestGeneratedCompatibilityMatrix` in `click_qa/compat_force_correct_text_stream_m4_dataflow/files/testcase.py`, equivalently every collected pytest id below `click_qa/compat_force_correct_text_stream_m4_dataflow/files/testcase.py::TestGeneratedCompatibilityMatrix`. Pytest identifies these methods by their full pytest ids and runs them in its normal ascending method-name order. Aggregate the requested counts over ALL test methods in that class, not over only one method. During that complete run, consider every invocation of the target function `click._compat._force_correct_text_stream` in the repository file `src/click/_compat.py`.

Report all dynamically observed def-use pairs for exactly these nine tracked local variables in `_force_correct_text_stream`: `binary_reader`, `encoding`, `errors`, `find_binary`, `force_readable`, `force_writable`, `is_binary`, `possible_binary_reader`, and `text_stream`. A definition is a successful runtime binding of a tracked bare local name by parameter binding, plain assignment, annotated assignment, augmented assignment, or a loop or comprehension target. All seven parameters (`text_stream`, `encoding`, `errors`, `is_binary`, `find_binary`, `force_readable`, and `force_writable`) are defined at the target function's `def` line when each invocation begins. A plain assignment's right-hand-side uses occur before its new definition takes effect. Assignment to an attribute or subscript and mutation through a method use the base variable but do not define it. An augmented assignment such as the hypothetical `q += 1` first uses `q`'s reaching definition and then defines `q` at that statement's line. A tracked `for`-loop target would be defined once for each successfully obtained item before that iteration's body, and the names read to obtain the iterable are uses; a `while` condition only uses names. A comprehension target would likewise be defined once per obtained item in the comprehension's own scope, and loads in its iterable, filters, and element expression would be uses in the scope where Python evaluates them. This target contains no loop, comprehension, or augmented assignment, so those rules add no events here.

A use is one runtime evaluation of a tracked bare name in Python `Load` context in the target function's own frame, reached by that variable's most recent definition in the same invocation. Count repeated evaluations separately even on one source line: evaluating a hypothetical `q + q` once would make two observations of the same pair. A condition contributes uses every time it is evaluated. Loading a tracked callable to call it, or a tracked object as a call argument, method receiver, subscript base, or iterable, is a use. Calls made by the target do not make their callee frames part of this accounting; only the target-frame name loads in the call expression count. Merely inspecting or displaying frame locals is not a use.

An invocation means one Python `call` of `click._compat._force_correct_text_stream` during the complete class run. Number invocations from 1 in chronological call order if instrumentation is used to distinguish their reaching definitions, but do not include invocation numbers in the answer. Definitions never reach across invocations. One observation is one executed use event reached by one definition, so a repeatedly executed use contributes once per actual evaluation. `count` is the total number of observations of that exact `(variable, def_line, use_line)` triple summed across every invocation in every test method in the class.

Both `def_line` and `use_line` are absolute 1-based source line numbers in `src/click/_compat.py` as checked out. For a multi-line statement or expression, use the line where the relevant definition target or loaded name expression begins; parameters are defined at the line where the multi-line `def` statement begins. Decorator and docstring lines are not definitions or uses unless they independently evaluate a tracked name under the rules above.

Return exactly `{"observed_def_use_pairs": [{"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}]}`. Its value is a JSON array with one object for every observed triple and no object for a never-observed triple. Each object contains the variable name as a direct JSON string, not Python `repr()`, and `count`, `def_line`, and `use_line` as JSON integers. Sort objects ascending first by `variable` using Python string ordering, then by integer `def_line`, then by integer `use_line`. Emit each triple exactly once; `count` carries all multiplicity, so there are no duplicate rows. The array is non-empty, and no empty string, JSON null, or omitted field represents any value."""


def fail(message: str) -> None:
    raise RuntimeError(message)


def source_model(source_path: Path) -> tuple[int, dict[int, tuple[str, ...]], dict[int, tuple[str, ...]]]:
    if not source_path.exists():
        fail(f"target source does not exist: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == TARGET_NAME
    ]
    if len(functions) != 1:
        fail(f"expected exactly one top-level {TARGET_NAME}, found {len(functions)}")

    function = functions[0]
    parameters = {
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
    }
    if function.args.vararg is not None:
        parameters.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        parameters.add(function.args.kwarg.arg)

    expected_parameters = TRACKED_VARIABLES & parameters
    if expected_parameters != {
        "text_stream",
        "encoding",
        "errors",
        "is_binary",
        "find_binary",
        "force_readable",
        "force_writable",
    }:
        fail("target parameter set no longer matches the data-flow specification")

    uses: dict[int, list[str]] = {}
    definitions: dict[int, list[str]] = {}
    for statement in function.body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Name) or node.id not in TRACKED_VARIABLES:
                continue
            if isinstance(node.ctx, ast.Load):
                uses.setdefault(node.lineno, []).append(node.id)
            elif isinstance(node.ctx, ast.Store):
                definitions.setdefault(node.lineno, []).append(node.id)

    return (
        function.lineno,
        {line: tuple(names) for line, names in uses.items()},
        {line: tuple(names) for line, names in definitions.items()},
    )


def parse_trace(trace_path: Path, source_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    parameter_line, uses_by_line, definitions_by_line = source_model(source_path)
    event_pattern = re.compile(
        r"^.* (?P<file>\S+):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    current_definitions: dict[str, int] | None = None
    observations: Counter[tuple[str, int, int]] = Counter()
    target_events = 0
    target_calls = 0
    target_returns = 0
    encoding_is_none: bool | None = None

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.match(raw_line)
        if match is None:
            continue
        filename = match.group("file").replace("\\", "/")
        function = match.group("func")
        if not filename.endswith(TARGET_FILE_SUFFIX) or function != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        line = int(match.group("line"))
        if event == "call":
            if current_definitions is not None:
                fail("overlapping target invocations are not supported")
            _, separator, raw_locals = raw_line.rpartition(" locals=")
            if not separator:
                fail("target call event has no locals payload")
            try:
                call_locals = ast.literal_eval(raw_locals)
            except (SyntaxError, ValueError) as error:
                fail(f"invalid target call locals payload: {error}")
            if not isinstance(call_locals, dict) or "encoding" not in call_locals:
                fail("target call locals payload has no encoding")
            encoding_is_none = call_locals["encoding"] == "None"
            current_definitions = {
                variable: parameter_line
                for variable in TRACKED_VARIABLES
                if variable
                in {
                    "text_stream",
                    "encoding",
                    "errors",
                    "is_binary",
                    "find_binary",
                    "force_readable",
                    "force_writable",
                }
            }
            target_calls += 1
        elif event == "line":
            if current_definitions is None:
                fail(f"target line event at {line} occurred outside an invocation")
            for variable in uses_by_line.get(line, ()):
                if line == 257 and variable == "text_stream" and not encoding_is_none:
                    continue
                if variable not in current_definitions:
                    fail(f"use of {variable} at line {line} has no reaching definition")
                observations[(variable, current_definitions[variable], line)] += 1
            for variable in definitions_by_line.get(line, ()):
                current_definitions[variable] = line
        elif event == "exception":
            fail(f"target raised an exception at line {line}")
        elif event == "return":
            if current_definitions is None:
                fail("target return occurred without an invocation")
            current_definitions = None
            encoding_is_none = None
            target_returns += 1

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero calls for {TARGET_FUNC}")
    if target_calls != target_returns:
        fail(
            f"target call/return mismatch: {target_calls} calls, "
            f"{target_returns} returns"
        )
    if current_definitions is not None:
        fail("trace ended during an active target invocation")
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
    source_path = Path.cwd() / "src/click/_compat.py"

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
        "oracle_answer": parse_trace(arguments.trace_log, source_path),
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
