"""Parse the sys.settrace log into oracle.json for instance
context_get_catalog_s6_calls (S6_InterProceduralCFG).

The answer is the ordered sequence of calls to a fixed tracked set of
same-module functions that occur while the TARGET_INVOCATION-th (1-based,
chronological order of ``call`` events) invocation of
``kedro.framework.context.context.KedroContext._get_catalog`` is on the
call stack, i.e. between its ``call`` event and its matching ``return``
event.  Direct and transitive calls both count; recursive calls and
repeated calls each produce their own entry; nothing is de-duplicated.

The tracer runs on Python 3.9, where code objects have no ``co_qualname``,
so trace lines identify frames as ``module.co_name`` (the class or
enclosing-function component is lost).  The parser reconstructs the
canonical dotted qualname of every traced function by walking the AST of
the target source file (taken from the absolute path in the trace itself)
and fails loudly if any traced name is ambiguous.
"""

import argparse
import ast
import json
import os
import re
import sys

TARGET_FILE_REL = "kedro/framework/context/context.py"
MODULE_NAME = "kedro.framework.context.context"
TARGET_FUNC = "kedro.framework.context.context.KedroContext._get_catalog"
TARGET_INVOCATION = 2

TRACKED_FUNCS = [
    "kedro.framework.context.context._convert_paths_to_absolute_posix",
    "kedro.framework.context.context._is_relative_path",
    "kedro.framework.context.context._update_nested_dict",
    "kedro.framework.context.context._validate_transcoded_datasets",
    "kedro.framework.context.context.compose_classes",
    "kedro.framework.context.context.KedroContext.params",
    "kedro.framework.context.context.KedroContext._get_config_credentials",
    "kedro.framework.context.context.KedroContext._get_parameters",
    "kedro.framework.context.context.KedroContext._get_parameters.<locals>._add_param_to_params_dict",
]
TRACKED_SET = frozenset(TRACKED_FUNCS)

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} "
    r"(?P<file>\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>\w+)\b"
)

QUESTION = """When the pytest test
`kedro_qa/context_get_catalog_s6_calls/files/testcase.py::TestCatalogCallChain::test_tracked_call_order`
is executed, the read-only property
`kedro.framework.context.context.KedroContext.catalog` is accessed three
times on the same `KedroContext` instance. The instance is built over a
temporary Kedro project whose `conf/base/catalog.yml` and
`conf/base/parameters.yml` are regenerated programmatically (by a seeded
random generator) before each access, so the configuration shape differs
on every access. Each property access performs exactly one call to the
target function
`kedro.framework.context.context.KedroContext._get_catalog` (defined in
the repository file `kedro/framework/context/context.py`, lines 224-273),
so the target is invoked three times during the test run.

Definitions used in this question:

- Function identity is the dotted qualname derived from the source file's
  structure: `module.Class.method` for methods (example:
  `kedro.framework.context.context.KedroContext._get_parameters`),
  `module.function` for module-level functions (example:
  `kedro.framework.context.context.compose_classes`), and for a function
  nested inside another function the qualname includes the enclosing
  qualname followed by `.<locals>.` (example shape:
  `some.module.Outer.<locals>.inner`).
- Invocation counting: one invocation of the target is one entry into the
  target (one function call); invocations are numbered 1-based in
  chronological order of function entry during the test run.
- Call ordering: calls are ordered chronologically by their function-entry
  moments (the order in which the called functions' frames start
  executing), which is also the order in which a tracer's `call` events
  would be emitted.

The tracked set is EXACTLY these nine functions (all defined in
`kedro/framework/context/context.py`):

1. `kedro.framework.context.context._convert_paths_to_absolute_posix`
2. `kedro.framework.context.context._is_relative_path`
3. `kedro.framework.context.context._update_nested_dict`
4. `kedro.framework.context.context._validate_transcoded_datasets`
5. `kedro.framework.context.context.compose_classes`
6. `kedro.framework.context.context.KedroContext.params`
7. `kedro.framework.context.context.KedroContext._get_config_credentials`
8. `kedro.framework.context.context.KedroContext._get_parameters`
9. `kedro.framework.context.context.KedroContext._get_parameters.<locals>._add_param_to_params_dict`

Task: report the ordered sequence of calls to tracked functions that occur
while invocation 2 of the target function
(`kedro.framework.context.context.KedroContext._get_catalog`) is on the
call stack. A call to a tracked function is included if and only if its
function-entry moment is after invocation 2 of the target is entered and
before invocation 2 of the target returns. This inclusion rule covers both
calls made directly from the target's own frame and transitive calls made
from any other function while invocation 2 of the target is still on the
stack (for example, calls that one tracked function makes to another
tracked function, including recursive self-calls). Every call is a
separate sequence entry: recursive calls and repeated calls to the same
tracked function each appear as their own element, in chronological order,
with no de-duplication and no re-sorting. Calls to functions outside the
tracked set are excluded entirely — this includes functions from other
modules (such as `kedro.pipeline.transcoding._transcode_split`), builtins,
methods of `DataCatalog`, hook calls, and the target function itself (the
sequence does not contain an entry for invocation 2 of the target).

Answer format: a JSON object with exactly one key, `function_call_order`,
whose value is a list with exactly one object per reported call, in call
order. Each object has exactly two keys: `file` (a JSON string giving the
repo-relative path of the file defining the called function — for every
call in this answer it is `kedro/framework/context/context.py`) and `func`
(a JSON string giving the dotted qualname of the called function, in the
format defined above, spelled exactly as in the tracked-set list).
"""


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def build_qualname_map(source_path: str) -> dict:
    """Map each function's co_name to its canonical dotted qualname(s),
    derived from the source file structure."""
    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=source_path)

    mapping: dict[str, set] = {}

    def walk(node, parts, inside_function):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, parts + [child.name], False)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual_parts = list(parts)
                if inside_function:
                    qual_parts.append("<locals>")
                qual_parts.append(child.name)
                mapping.setdefault(child.name, set()).add(
                    MODULE_NAME + "." + ".".join(qual_parts)
                )
                walk(child, qual_parts, True)
            else:
                walk(child, parts, inside_function)

    walk(tree, [], False)
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.trace_log):
        fail(f"trace log not found: {args.trace_log}")
    if os.path.getsize(args.trace_log) == 0:
        fail(f"trace log is empty: {args.trace_log}")

    events = []
    source_path = None
    total_line_events = 0
    distinct_lines = set()
    call_events = 0
    distinct_called = set()

    with open(args.trace_log, encoding="utf-8") as fh:
        for raw in fh:
            m = LINE_RE.match(raw)
            if not m:
                continue
            abs_file = m.group("file").replace("\\", "/")
            if not abs_file.endswith(TARGET_FILE_REL):
                fail(f"unexpected traced file path: {abs_file}")
            if source_path is None:
                source_path = abs_file
            func_field = m.group("func")
            if not func_field.startswith(MODULE_NAME + "."):
                fail(f"unexpected traced function name: {func_field}")
            co_name = func_field[len(MODULE_NAME) + 1:]
            if "." in co_name:
                fail(f"unexpected dotted co_name in trace: {func_field}")
            event = m.group("event")
            lineno = int(m.group("line"))
            events.append((co_name, event, lineno))
            if event == "line":
                total_line_events += 1
                distinct_lines.add(lineno)
            elif event == "call":
                call_events += 1
                distinct_called.add(co_name)

    if not events:
        fail("no trace events for the target file")
    if total_line_events == 0:
        fail("zero executed line events in trace log")
    if source_path is None or not os.path.isfile(source_path):
        fail(f"target source file not found: {source_path}")

    qualname_map = build_qualname_map(source_path)

    def canonical(co_name: str) -> str:
        quals = qualname_map.get(co_name)
        if not quals:
            fail(f"traced function {co_name!r} not found in target source AST")
        if len(quals) > 1:
            fail(f"ambiguous co_name {co_name!r}: {sorted(quals)}")
        return next(iter(quals))

    target_invocations = 0
    active = False
    sequence = []

    for co_name, event, _lineno in events:
        qual = canonical(co_name)
        if qual == TARGET_FUNC and event == "call":
            target_invocations += 1
            if target_invocations == TARGET_INVOCATION:
                if active:
                    fail("target re-entered while already active")
                active = True
            continue
        if not active:
            continue
        if qual == TARGET_FUNC and event == "return":
            active = False
            continue
        if event == "call":
            if qual not in TRACKED_SET:
                fail(f"unexpected non-tracked call while target active: {qual}")
            sequence.append({"file": TARGET_FILE_REL, "func": qual})

    if target_invocations == 0:
        fail(f"no call events for target function {TARGET_FUNC} in trace log")
    if target_invocations < TARGET_INVOCATION:
        fail(
            f"only {target_invocations} invocation(s) of target traced; "
            f"need invocation {TARGET_INVOCATION}"
        )
    if not sequence:
        fail(
            f"empty tracked call sequence for invocation {TARGET_INVOCATION} "
            "of target"
        )
    if len(sequence) < 10:
        fail(f"degenerate call sequence of length {len(sequence)}")
    if len({entry["func"] for entry in sequence}) < 3:
        fail("degenerate call sequence: fewer than 3 distinct tracked functions")

    print(f"target invocations traced: {target_invocations}")
    print(f"total line events: {total_line_events}")
    print(f"distinct executed lines: {len(distinct_lines)}")
    print(f"total call events: {call_events}")
    print(f"distinct called functions: {len(distinct_called)}")
    print(f"sequence length for invocation {TARGET_INVOCATION}: {len(sequence)}")
    print(
        "distinct tracked functions in sequence: "
        f"{len({entry['func'] for entry in sequence})}"
    )

    oracle_answer = {"function_call_order": sequence}
    template_answer = {"function_call_order": [{"file": "str", "func": "str"}]}
    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": template_answer,
        "oracle_answer": oracle_answer,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
