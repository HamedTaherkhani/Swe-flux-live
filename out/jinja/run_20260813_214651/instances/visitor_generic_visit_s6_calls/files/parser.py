#!/usr/bin/env python3
"""Parse trace log into oracle.json for visitor_generic_visit_s6_calls."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TARGET_REL_FILE = "src/jinja2/visitor.py"
TARGET_FUNC = "jinja2.visitor.NodeTransformer.generic_visit"
TARGET_DEF_LINE = 61
TARGET_INVOCATION = 1

TRACKED_FUNCS = frozenset(
    {
        "jinja2.visitor.NodeVisitor.visit",
        "jinja2.visitor.NodeVisitor.get_visitor",
    }
)

QUESTION = """\
During the pytest run identified by the test id \
`jinja_qa/visitor_generic_visit_s6_calls/files/testcase.py::TestGenericVisitCallOrder::test_visit_list_transform`, \
report the **function_call_order** for invocation **1** of the target function \
`jinja2.visitor.NodeTransformer.generic_visit` defined in `src/jinja2/visitor.py` \
(the `def generic_visit` line is line 61 in that file).

The test reaches this function **indirectly**: it parses a Jinja template into an AST, \
constructs a `NodeTransformer` subclass, and calls `visit_list` on the root template node. \
That entry point calls `visit`, which dispatches into `generic_visit` when no dedicated \
`visit_*` handler exists. The test never calls `generic_visit` directly.

**Invocation numbering:** an invocation is one `call` trace event whose qualified function \
name is exactly `jinja2.visitor.NodeTransformer.generic_visit` and whose line number is \
exactly 61 (the `def` line). Number invocations **1-based** in chronological order of those \
events across the entire pytest run. Ignore `call` events for `generic_visit` at any other \
line number.

**Tracked functions** (only these two; report each using the dotted qualname format \
`module.Class.method`, for example `jinja2.visitor.NodeVisitor.visit`):

1. `jinja2.visitor.NodeVisitor.visit`
2. `jinja2.visitor.NodeVisitor.get_visitor`

**Inclusion rule:** collect every `call` trace event whose qualified name is one of the \
tracked functions above that occurs while invocation 1 of \
`jinja2.visitor.NodeTransformer.generic_visit` is on the Python call stack. Concretely, \
the invocation-1 `generic_visit` frame has been entered via its line-61 `call` event and \
its matching `return` event has not yet been processed. Nested and transitive calls count: \
when invocation 1's `generic_visit` calls `visit` and `visit` calls `get_visitor`, both \
`call` events are included. Calls made after invocation 1's `generic_visit` returns are \
excluded even if they occur later in the test. Calls to functions outside the tracked set, \
builtins, comprehension frames, and generator resumptions are excluded. Repeated calls are \
all included; do not deduplicate.

**Ordering:** preserve the chronological order of qualifying `call` events exactly as they \
occur during execution. Do not sort or reorder.

Each `function_call_order` element is an object with two keys:

- `file`: repo-relative path, always the exact string `src/jinja2/visitor.py` for every entry.
- `func`: the fully qualified function name exactly as traced (`module.qualname`), e.g. \
`jinja2.visitor.NodeVisitor.get_visitor`.

Return JSON with top-level key `function_call_order` whose value is the list described above.\
"""

EVENT_RE = re.compile(
    r"(?P<file>[^:]+):(?P<line>\d+) "
    r"(?P<func>\S+) "
    r"event=(?P<event>\w+)"
)


def _parse_trace_events(trace_log: Path) -> list[tuple[str, str, int, str]]:
    if not trace_log.is_file():
        raise SystemExit(f"ERROR: trace log not found: {trace_log}")

    text = trace_log.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_log}")

    events: list[tuple[str, str, int, str]] = []
    for line in text.splitlines():
        match = EVENT_RE.search(line)
        if match is None:
            continue
        events.append(
            (
                match.group("event"),
                match.group("func"),
                int(match.group("line")),
                match.group("file"),
            )
        )

    if not events:
        raise SystemExit(f"ERROR: no parseable trace events in: {trace_log}")

    return events


def _compute_function_call_order(
    events: list[tuple[str, str, int, str]],
) -> list[dict[str, str]]:
    target_events = [
        e
        for e in events
        if e[1] == TARGET_FUNC
        and e[0] in {"call", "line", "return", "exception"}
    ]
    if not target_events:
        raise SystemExit(
            f"ERROR: zero trace events for target function {TARGET_FUNC}"
        )

    stack: list[tuple[str, int | None]] = []
    gv_invocation = 0
    order: list[dict[str, str]] = []

    for event, func, lineno, _file in events:
        if event == "call":
            if func == TARGET_FUNC and lineno == TARGET_DEF_LINE:
                gv_invocation += 1
                stack.append((func, gv_invocation))
            else:
                stack.append((func, None))

            if func in TRACKED_FUNCS:
                on_stack = any(
                    frame_func == TARGET_FUNC
                    and frame_inv == TARGET_INVOCATION
                    for frame_func, frame_inv in stack[:-1]
                )
                if on_stack:
                    order.append(
                        {
                            "file": TARGET_REL_FILE,
                            "func": func,
                        }
                    )
        elif event in ("return", "exception"):
            if not stack:
                raise SystemExit("ERROR: return/exception event with empty stack")
            stack.pop()

    if gv_invocation < TARGET_INVOCATION:
        raise SystemExit(
            f"ERROR: only {gv_invocation} invocations of {TARGET_FUNC}; "
            f"need at least {TARGET_INVOCATION}"
        )

    if not order:
        raise SystemExit(
            "ERROR: no qualifying tracked function calls for target invocation"
        )

    return order


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    events = _parse_trace_events(args.trace_log)
    answer = _compute_function_call_order(events)

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}],
        },
        "oracle_answer": {
            "function_call_order": answer,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote oracle with {len(answer)} call-order entries to {args.out}")


if __name__ == "__main__":
    main()
