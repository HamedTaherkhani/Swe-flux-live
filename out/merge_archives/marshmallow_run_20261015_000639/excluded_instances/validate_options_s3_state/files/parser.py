"""Parse the line trace of OneOf.options into oracle.json (S3_ProgramState)."""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE = "src/marshmallow/validate.py"
TARGET_FUNC = "marshmallow.validate.OneOf.options"
VARIABLE = "padded_labels"
TEST_ID = (
    "marshmallow_qa/validate_options_s3_state/files/testcase.py"
    "::OneOfOptionsTest::test_options_label_padding"
)

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_lines(root):
    """Locate the padded_labels assignment and the return statement in OneOf.options."""
    path = os.path.join(root, TARGET_FILE)
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "OneOf":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "options":
                    assign = ret = None
                    for stmt in item.body:
                        if isinstance(stmt, ast.Assign) and any(
                            isinstance(t, ast.Name) and t.id == VARIABLE
                            for t in stmt.targets
                        ):
                            assign = stmt.lineno
                        if isinstance(stmt, ast.Return):
                            ret = stmt.lineno
                    if assign and ret:
                        return assign, ret
    die("could not locate OneOf.options statements in source")


def parse_locals(rest):
    idx = rest.find("locals=")
    if idx < 0:
        return {}
    try:
        return ast.literal_eval(rest[idx + len("locals="):])
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=os.getcwd())
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log) or os.path.getsize(args.trace_log) == 0:
        die(f"trace log missing or empty: {args.trace_log}")

    assign_line, return_line = find_lines(args.root)

    history = []
    state = None
    captured = False
    n_events = 0
    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = EVENT_RE.match(raw.rstrip("\n"))
            if not m or m.group("func") != TARGET_FUNC:
                continue
            if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
                continue
            n_events += 1
            event = m.group("event")
            line = int(m.group("line"))
            loc = parse_locals(m.group("rest"))
            if event == "call":
                state = dict(loc)
                captured = False
                continue
            if state is None:
                die("event before call in trace")
            state.update(loc)
            if event == "line" and line == return_line and not captured:
                if VARIABLE not in state:
                    die("padded_labels not bound when return line reached")
                history.append(state[VARIABLE])
                captured = True
            if event == "return":
                if not captured:
                    die("invocation returned without reaching return line")
                state = None

    if n_events == 0:
        die("no events for target function in trace")
    if not history:
        die("no observations harvested")

    question = f"""\
Test: `{TEST_ID}` (test class `OneOfOptionsTest`, single test method `test_options_label_padding`).
Target function: `marshmallow.validate.OneOf.options` defined in `{TARGET_FILE}`.

During this test run, `OneOf.options` is invoked several times. An invocation is one call of \
`OneOf.options` (only frames of the function `OneOf.options` itself count; the generator expression it returns is not an invocation). Invocations are \
counted 1-based in chronological order of their call over the whole test run.

For each invocation, observe the local variable `{VARIABLE}` immediately after the (multi-line) \
assignment statement `{VARIABLE} = labels[: len(choices)] + ...` that begins on line {assign_line} \
of `{TARGET_FILE}` has finished executing (equivalently: at the moment the `return` statement that \
begins on line {return_line} starts executing in that invocation). Line numbers are absolute, 1-based, \
in the file as it exists in the repository.

Answer format: a JSON object `{{"value_history": [{{"step": int, "value": str}}, ...]}}` with exactly one \
entry per invocation of `OneOf.options` during the test, ordered by ascending `step`, no deduplication \
(identical values in different invocations are each listed). `step` is the 1-based invocation index \
(first invocation is 1). `value` is the Python `repr()` of the whole tuple held by `{VARIABLE}` at the \
observation point, exactly as `repr()` produces it: strings inside keep their single quotes, elements \
are separated by `, `, an empty tuple is `()` and a one-element tuple keeps its trailing comma \
(e.g. a tuple with the single string x would be `('x',)`; a tuple with three empty strings would be `('', '', '')`)."""

    oracle = {
        "question_kind": "S3_ProgramState",
        "question": question,
        "template_answer": {"value_history": [{"step": "int", "value": "str"}]},
        "oracle_answer": {
            "value_history": [
                {"step": i + 1, "value": v} for i, v in enumerate(history)
            ]
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print(json.dumps(oracle["oracle_answer"], indent=2))


if __name__ == "__main__":
    main()
