#!/usr/bin/env python3
import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "fastapi/applications.py"
TARGET_FUNC = "fastapi.applications.FastAPI.setup"

EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run the pytest test
`fastapi_qa/applications_setup_m1_cfg/files/testcase.py::TestApplicationSetupControlFlow::test_generated_setup_matrix_and_handlers`
against this repository. Consider the runtime code region of
`fastapi.applications.FastAPI.setup` in `fastapi/applications.py`, including
both the `FastAPI.setup` frame and frames of local functions lexically defined
inside that method. In exact dotted-name terms, retain frames whose name is
either `fastapi.applications.FastAPI.setup` or begins with
`fastapi.applications.FastAPI.setup.<locals>.`; this includes the local route
handlers and their comprehension frames. Exclude every other frame, including
methods called by `setup` and functions called by those local handlers.

What is the set of source lines covered in that region across the whole named
test? Return exactly `{"covered_lines": ["int"]}`. `covered_lines` must be a
JSON list of integers, sorted in strictly ascending numeric order. Include each
line at most once: deduplicate events across repeated executions, across all
invocations, and across all retained frames.

An invocation of `FastAPI.setup` means one call of exactly its own frame,
counted 1-based in chronological order; calls of its local functions and other
frames are not additional `setup` invocations. Coverage nevertheless combines
the line events from every `setup` invocation and every retained local-function
invocation during the test. Count only Python runtime `line` events; exclude
`call`, `return`, and `exception` events. A line number is absolute, 1-based,
and refers to `fastapi/applications.py` as it exists in this checkout.

For a multi-line statement or expression, report the line where its innermost
enclosing Python statement begins, rather than a continuation line.
Specifically, normalize each line event to the `lineno` of the enclosing
`ast.stmt` node with the smallest inclusive `lineno` through `end_lineno`
span; ties choose the node with the later starting line, then the smaller
column offset. For example, an event on a later argument of a multi-line call
is reported as the line where the statement containing that call starts.
Decorator and `def` lines do not count merely because a function is called or
defined; they can appear only if they independently produce a retained `line`
event. A docstring line likewise appears only if it produces such an event.
There is no string-value formatting or null/empty sentinel in the answer:
every list element is a JSON integer."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def locate_setup(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FastAPI":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "setup":
                    return child
    fail("could not locate FastAPI.setup in target source")


def statement_start_map(source_path: Path) -> tuple[dict[int, int], range]:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")
    tree = ast.parse(source, filename=str(source_path))
    target = locate_setup(tree)
    if target.end_lineno is None:
        fail("FastAPI.setup has no end line in parsed source")

    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt)
        and node is not target
        and node.end_lineno is not None
    ]
    mapping = {}
    for line in range(target.lineno + 1, target.end_lineno + 1):
        enclosing = [
            node for node in statements if node.lineno <= line <= node.end_lineno
        ]
        if enclosing:
            chosen = min(
                enclosing,
                key=lambda node: (
                    node.end_lineno - node.lineno,
                    -node.lineno,
                    node.col_offset,
                ),
            )
            mapping[line] = chosen.lineno
    return mapping, range(target.lineno, target.end_lineno + 1)


def is_retained_function(name: str) -> bool:
    return name == TARGET_FUNC or name.startswith(f"{TARGET_FUNC}.<locals>.")


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    trace_text = trace_path.read_text(encoding="utf-8")
    if not trace_text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    source_path = None
    for raw_line in trace_text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match or not is_retained_function(match.group("func")):
            continue
        traced_file = Path(match.group("file"))
        if not traced_file.as_posix().endswith(TARGET_FILE):
            fail(f"retained event came from unexpected file: {traced_file}")
        source_path = traced_file
        events.append(
            (
                match.group("func"),
                match.group("event"),
                int(match.group("line")),
            )
        )

    if not events:
        fail(f"trace contains zero events for the {TARGET_FUNC} code region")
    if source_path is None:
        fail("could not determine target source path from trace")

    setup_paths = []
    current_path = None
    for func, event, line in events:
        if func != TARGET_FUNC:
            continue
        if event == "call":
            if current_path is not None:
                fail("encountered overlapping FastAPI.setup invocations")
            current_path = set()
        elif event == "line":
            if current_path is None:
                fail("FastAPI.setup line event appeared outside an invocation")
            current_path.add(line)
        elif event == "return":
            if current_path is None:
                fail("FastAPI.setup return appeared without a call")
            setup_paths.append(current_path)
            current_path = None
    if current_path is not None:
        fail("final FastAPI.setup invocation has no return event")
    if len(setup_paths) < 3:
        fail(f"trace has only {len(setup_paths)} completed setup invocations")
    if len({frozenset(path) for path in setup_paths}) < 3:
        fail("trace does not contain three distinct FastAPI.setup paths")

    line_map, target_span = statement_start_map(source_path)
    covered = set()
    line_event_count = 0
    for _func, event, line in events:
        if event != "line":
            continue
        line_event_count += 1
        if line not in target_span:
            fail(f"retained line event {line} is outside FastAPI.setup source span")
        if line not in line_map:
            fail(f"line event {line} is not enclosed by a setup-region statement")
        covered.add(line_map[line])

    if line_event_count == 0:
        fail("retained target region contains zero line events")
    covered_lines = sorted(covered)
    if len(covered_lines) < 25:
        fail(f"covered-line answer is too small: {len(covered_lines)} values")

    output = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": {"covered_lines": ["int"]},
        "oracle_answer": {"covered_lines": covered_lines},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote oracle with {len(covered_lines)} covered lines "
        f"from {line_event_count} line events to {out_path}"
    )


if __name__ == "__main__":
    main()
