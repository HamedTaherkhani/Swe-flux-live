from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path


MODULE = "scrapy.extensions.httpcache"
TARGET_CLASS = "RFC2616Policy"
TARGET_METHOD = f"{MODULE}.{TARGET_CLASS}.is_cached_response_fresh"
TARGET_FILE = "scrapy/extensions/httpcache.py"

EVENT_RE = re.compile(
    r"(?P<file>/\S*scrapy/extensions/httpcache\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)(?:\s|$)"
)

QUESTION = """Run pytest on every test item selected by
`scrapy_qa/httpcache_is_cached_response_fresh_m6_calls/files/testcase.py::TestRFC2616FreshnessCallGraph`.
Aggregate the result across ALL `test_*` methods in that class; each covered
test item is identified by its full pytest id
`scrapy_qa/httpcache_is_cached_response_fresh_m6_calls/files/testcase.py::TestRFC2616FreshnessCallGraph::test_method_name`.
Count activity during each complete selected test item, including its
`unittest.TestCase.setUp` execution, test body, and registered cleanup
callbacks.

The primary target is
`scrapy.extensions.httpcache.RFC2616Policy.is_cached_response_fresh`, defined
in `scrapy/extensions/httpcache.py`.  The tracked scope is every synchronous
or asynchronous function defined directly in the body of class
`RFC2616Policy` in that file.  Include `__init__`, all other dunder methods,
and decorated methods or property accessors when their `def`/`async def` is a
direct class-body statement.  Exclude inherited methods, module-level
functions, nested classes and their methods, and nested functions, closures,
lambda bodies, and comprehension frames inside a method.  Calls to excluded
functions can cause later in-scope calls but do not receive answer rows.

Function identity is the dotted `module.qualname`, for example
`pkg.mod.Widget.run`.  The `file` value is the forward-slash,
repository-relative path of the file containing the definition.  Emit
ordinary JSON strings for `file` and `func` and JSON integers for `count`;
there are no `null` or omitted values.

One invocation means one Python `call` trace event for that in-scope
function's frame during any selected test item.  Count calls originating from
any frame, including direct, transitive, and recursive calls, and do not
deduplicate events.  A generator or coroutine resumption that produces
another Python `call` event counts as another invocation.  Sum all such events
across all selected test methods rather than reporting per-method values.

Return exactly
`{"invocation_counts": [{"count": int, "file": str, "func": str}, ...]}`.
Produce exactly one row for each distinct function qualname in the tracked
scope.  A scoped function that never executes must still appear with
`count: 0`.  Sort rows by `func` ascending; if two rows have the same `func`,
break the tie by `file` ascending.  Counts are aggregated, but answer rows are
not otherwise deduplicated or reordered."""


def scoped_functions(source_path: Path) -> list[str]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"cannot parse target source {source_path}: {exc}") from exc

    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == TARGET_CLASS
        ),
        None,
    )
    if class_node is None:
        raise RuntimeError(f"class {TARGET_CLASS} not found in {source_path}")

    names = sorted(
        {
            f"{MODULE}.{TARGET_CLASS}.{node.name}"
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
    )
    if not names:
        raise RuntimeError(f"no directly defined methods found for {TARGET_CLASS}")
    return names


def parse_counts(trace_path: Path, funcs: list[str]) -> Counter[str]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    scoped = set(funcs)
    counts: Counter[str] = Counter()
    target_events = 0
    parsed_events = 0
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(line)
        if match is None:
            continue
        parsed_events += 1
        func = match.group("func")
        if func == TARGET_METHOD:
            target_events += 1
        if match.group("event") == "call" and func in scoped:
            counts[func] += 1

    if parsed_events == 0:
        raise RuntimeError("trace log contains no parseable target-file events")
    if target_events == 0:
        raise RuntimeError(
            f"trace log contains zero events for target function {TARGET_METHOD}"
        )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    source_path = Path.cwd() / TARGET_FILE
    funcs = scoped_functions(source_path)
    counts = parse_counts(args.trace_log, funcs)
    invocation_counts = [
        {"count": counts[func], "file": TARGET_FILE, "func": func}
        for func in funcs
    ]
    invocation_counts.sort(key=lambda row: (row["func"], row["file"]))

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
        },
        "oracle_answer": {"invocation_counts": invocation_counts},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["oracle_answer"], sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
