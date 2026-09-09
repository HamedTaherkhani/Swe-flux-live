#!/usr/bin/env python3
import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "haystack/components/connectors/openapi_service.py"
TARGET_FUNC = "haystack.components.connectors.openapi_service._invoke_method"
TARGET_METHOD = "_invoke_method"
TRACKED_VARIABLES = (
    "invocation_arguments",
    "method_call_params",
    "method_invocation_descriptor",
    "method_to_call",
    "name",
    "openapi_service",
    "operation",
    "operation_dict",
    "param",
    "param_name",
    "param_value",
    "parameters",
    "request_body",
    "required_params",
    "schema",
    "self",
)

QUESTION = """Run the pytest class node `haystack_qa/openapi_service_invoke_method_m4_dataflow/files/testcase.py::TestOpenAPIInvokeDataFlow`, which selects and aggregates ALL `test_...` methods defined on that class. A test is identified by its full pytest id `haystack_qa/openapi_service_invoke_method_m4_dataflow/files/testcase.py::TestOpenAPIInvokeDataFlow::<method_name>`; the requested counts are totals across all selected methods, independent of the order in which pytest runs them.

For every invocation of `haystack.components.connectors.openapi_service.OpenAPIServiceConnector._invoke_method` in `haystack/components/connectors/openapi_service.py` during that complete class run, compute the observed reaching-definition/use pairs for exactly these tracked local variables: `invocation_arguments`, `method_call_params`, `method_invocation_descriptor`, `method_to_call`, `name`, `openapi_service`, `operation`, `operation_dict`, `param`, `param_name`, `param_value`, `parameters`, `request_body`, `required_params`, `schema`, and `self`. An invocation is one `call` of this function; invocations are numbered from 1 in chronological order, although the invocation number is not included in the answer.

A definition is a runtime write of a tracked variable under these rules. Every parameter, including `self`, is defined when the call begins, at the function's `def` line. A plain or annotated assignment to a name defines that name after its right-hand side has completed. A `for` target is defined at the loop-header line once for each successful item retrieval, before that iteration's body; an exhaustion check does not define it. The iterable expression on a `for` header is evaluated, and hence contributes uses, only once when that loop is entered. Iteration N means the Nth successful item retrieval for that particular loop in that invocation. An assignment through a subscript whose root object is the tracked name `method_call_params` both uses the prior state of `method_call_params` and, after the assignment completes, defines its new container state at that assignment's line. Other attribute or subscript writes do not define a tracked name. If augmented assignment were present, it would first use the old target value and then define the new value after the operation. A comprehension has its own implicit scope: a comprehension target would not define an enclosing tracked local, while tracked names evaluated in the comprehension's outer iterable or expressions would be uses according to normal Python evaluation. There are no comprehension-target variables in the tracked list.

A use is one actually evaluated source-level `Name` load of a tracked variable. Short-circuited operands and statements skipped by control flow contribute no uses. If a tracked name occurs twice in evaluated expressions on one source line, those are two use observations. A use is paired with the most recent definition of the same variable in that invocation that precedes that evaluation. Definitions do not carry between invocations. An observation is one such evaluated use reached by one definition, so a use in a loop body counts once per iteration in which it is evaluated. If execution raises before a later expression is evaluated or before a write completes, that later use or definition does not occur.

All line numbers are absolute, 1-based line numbers in the named repository file as it exists for this run. A multi-line statement or expression is attributed to the physical source line on which the relevant name load or assignment target begins. Parameter definitions are attributed to the `def` line; decorator and docstring lines contribute nothing because they are not evaluated in an invocation.

Return exactly one JSON object with the shape `{"observed_def_use_pairs": [{"count": 1, "def_line": 8, "use_line": 9, "variable": "buffer"}]}` (the shown object is only a format example and is not part of the answer). Each row has exactly four fields: `variable` is the source-level variable name as a JSON string, while `def_line`, `use_line`, and `count` are JSON integers. `count` is the total number of observations of that exact `(variable, def_line, use_line)` triple across all invocations in all test methods. Emit one row for each triple with a positive count and no row for an unobserved triple. The triple is unique in the list: multiplicity appears only in `count`, never as duplicate rows. Sort rows ascending by `variable` in Unicode code-point order, then by `def_line` numerically, then by `use_line` numerically. There are no representations, exception names, missing values, empty strings, or JSON nulls in this answer."""

EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)(?: |$)"
)


def parse_locals(raw_line):
    marker = " locals="
    if marker not in raw_line:
        raise ValueError(f"target event has no locals field: {raw_line.rstrip()}")
    value = ast.literal_eval(raw_line.split(marker, 1)[1].strip())
    if not isinstance(value, dict):
        raise ValueError("target event locals field is not a dictionary")
    return value


def root_name(node):
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def source_model(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TARGET_METHOD
        ),
        None,
    )
    if function is None:
        raise ValueError(f"could not locate {TARGET_METHOD} in {source_path}")

    tracked = set(TRACKED_VARIABLES)
    uses = Counter()
    definitions = {}
    loop_targets = {}

    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in tracked:
            uses[(node.lineno, node.id)] += 1

        targets = []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in tracked:
                definitions.setdefault(target.lineno, []).append(target.id)
            elif isinstance(target, ast.Subscript):
                name = root_name(target)
                if name == "method_call_params":
                    definitions.setdefault(target.lineno, []).append(name)

        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            if node.target.id in tracked:
                first_body_line = min(item.lineno for item in node.body)
                loop_targets[node.lineno] = (node.target.id, first_body_line)

    parameters = [
        argument.arg
        for argument in (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
        )
        if argument.arg in tracked
    ]
    return function.lineno, parameters, uses, definitions, loop_targets


def literal_truth(value_repr):
    try:
        return bool(ast.literal_eval(value_repr))
    except (ValueError, SyntaxError):
        return True


def read_invocations(trace_path):
    if not trace_path.exists():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise ValueError(f"trace log is empty: {trace_path}")

    invocations = []
    current = None
    target_events = 0
    with trace_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            match = EVENT_RE.search(raw_line)
            if not match or match.group("func") != TARGET_FUNC:
                continue
            if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
                continue
            target_events += 1
            event = match.group("event")
            record = (event, int(match.group("line")), parse_locals(raw_line))
            if event == "call":
                if current is not None:
                    raise ValueError("encountered a nested or unterminated target invocation")
                current = [record]
                invocations.append(current)
            elif current is None:
                raise ValueError("target event appeared before its call event")
            else:
                current.append(record)
                if event == "return":
                    current = None

    if target_events == 0:
        raise ValueError(f"trace contains zero events for {TARGET_FUNC}")
    if not invocations:
        raise ValueError(f"trace contains no call event for {TARGET_FUNC}")
    return invocations


def harvest(trace_path, source_path):
    def_line, parameters, uses, definitions, loop_targets = source_model(source_path)
    counts = Counter()

    for invocation in read_invocations(trace_path):
        reaching = {name: def_line for name in parameters}
        state = {}
        loop_seen = set()
        line_records = [(line, changed) for event, line, changed in invocation if event == "line"]

        for index, (line, changed) in enumerate(line_records):
            state.update(changed)
            next_line = line_records[index + 1][0] if index + 1 < len(line_records) else None

            for (use_line, variable), multiplicity in uses.items():
                if use_line != line:
                    continue
                if line in loop_targets and line in loop_seen:
                    continue
                if line == 355 and variable == "invocation_arguments":
                    if not literal_truth(state.get("name", "None")):
                        continue
                if variable not in reaching:
                    raise ValueError(
                        f"use of {variable} at line {line} has no reaching definition"
                    )
                counts[(variable, reaching[variable], line)] += multiplicity

            if line in loop_targets:
                variable, first_body_line = loop_targets[line]
                loop_seen.add(line)
                if next_line == first_body_line:
                    reaching[variable] = line

            for variable in definitions.get(line, []):
                reaching[variable] = line

    if not counts:
        raise ValueError("computed no observed def-use pairs")

    return [
        {
            "count": count,
            "def_line": def_line,
            "use_line": use_line,
            "variable": variable,
        }
        for (variable, def_line, use_line), count in sorted(counts.items())
    ]


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    if not source_path.is_file():
        raise FileNotFoundError(f"target source is missing: {source_path}")

    observed = harvest(Path(args.trace_log), source_path)
    payload = {
        "question_kind": "M4_DataFlow",
        "question": QUESTION,
        "template_answer": {
            "observed_def_use_pairs": [
                {"count": "int", "def_line": "int", "use_line": "int", "variable": "str"}
            ]
        },
        "oracle_answer": {"observed_def_use_pairs": observed},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["oracle_answer"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
