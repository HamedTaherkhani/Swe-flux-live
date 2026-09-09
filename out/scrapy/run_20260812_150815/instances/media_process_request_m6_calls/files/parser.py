from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "scrapy/pipelines/media.py"
MODULE = "scrapy.pipelines.media"
SCOPE_CLASS = "MediaPipeline"
TARGET_FUNC = f"{MODULE}.{SCOPE_CLASS}._process_request"

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def scoped_functions(source_path: Path) -> list[str]:
    if not source_path.exists():
        fail(f"target source is missing: {source_path}")

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == SCOPE_CLASS
        ),
        None,
    )
    if class_node is None:
        fail(f"class {SCOPE_CLASS} not found in {source_path}")

    names: list[str] = []

    def collect_class(node: ast.ClassDef, class_qualname: str) -> None:
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(f"{MODULE}.{class_qualname}.{child.name}")
            elif isinstance(child, ast.ClassDef):
                collect_class(child, f"{class_qualname}.{child.name}")

    collect_class(class_node, SCOPE_CLASS)
    if TARGET_FUNC not in names:
        fail(f"target function {TARGET_FUNC} is not in the computed scope")
    return sorted(set(names))


def invocation_counts(trace_path: Path, functions: list[str]) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    scoped = set(functions)
    counts: Counter[str] = Counter()
    target_events = 0
    target_calls = 0

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        file_name = match.group("file").replace("\\", "/")
        func = match.group("func")
        event = match.group("event")
        if not file_name.endswith(f"/{TARGET_FILE}"):
            continue
        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                target_calls += 1
        if event == "call" and func in scoped:
            counts[func] += 1

    if target_events == 0:
        fail(f"trace contains zero events for target function {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero call events for target function {TARGET_FUNC}")

    entries = [
        {"count": counts[func], "file": TARGET_FILE, "func": func}
        for func in functions
    ]
    entries.sort(key=lambda entry: (str(entry["func"]), str(entry["file"])))
    return {"invocation_counts": entries}


def question_text() -> str:
    return (
        "Run pytest on "
        "`scrapy_qa/media_process_request_m6_calls/files/testcase.py::"
        "MediaProcessRequestCallCountsTest`, which selects every collected test "
        "method in that class, including the setup and teardown phases associated "
        "with each method. The selected methods are exactly the methods in that "
        "class whose names begin with `test_`; each individual pytest id is formed "
        "as `<file>::MediaProcessRequestCallCountsTest::<method-name>`. Aggregate "
        "the counts across the complete run of all those test ids, rather than "
        "reporting per-method counts. The primary target reached by these tests is "
        "`scrapy.pipelines.media.MediaPipeline._process_request` in "
        "`scrapy/pipelines/media.py`.\n\n"
        "For this run, consider every synchronous or asynchronous function or "
        "method definition lexically contained in the body of class "
        "`MediaPipeline` in `scrapy/pipelines/media.py`, including definitions in "
        "classes nested within `MediaPipeline`. Include `__init__`, every other "
        "dunder method, abstract-method definitions, and property getter, setter, "
        "or deleter functions if present. Exclude module-level functions, methods "
        "in subclasses or base classes outside that class body, inherited methods, "
        "comprehension frames, and functions or closures nested inside a method. "
        "A subclass override does not count as execution of the corresponding "
        "`MediaPipeline` definition unless the latter definition's own code frame "
        "actually executes.\n\n"
        "Function identity is the executing code object's dotted qualname prefixed "
        "by its module, in the exact form `module.Class.method`; for example, "
        "`demo.worker.Job.run`. Nested classes retain every class component in the "
        "qualname. Report names as plain JSON strings, without `repr()` quotes, "
        "abbreviation, or path-derived renaming. One invocation means one Python "
        "`call` event for that exact function frame while any selected test id is "
        "running. Count calls regardless of the caller: direct, transitive, and "
        "recursive calls all qualify. Preserve repeated calls; do not deduplicate "
        "events. Under Python's tracing semantics, resuming a suspended generator "
        "or coroutine frame emits another `call` event, and each such resumption "
        "therefore counts as another invocation. Calls to out-of-scope functions, "
        "built-ins, comprehension frames, and subclass overrides are not counted.\n\n"
        "Return exactly one JSON object with the single key `invocation_counts`. "
        "Its value is a JSON array containing one object for every in-scope "
        "definition, including a never-executed function with integer `count: 0`. "
        "Each object has exactly three keys: `count`, a non-negative JSON integer "
        "equal to the summed invocation count; `file`, the plain forward-slash "
        "repository-relative JSON string `scrapy/pipelines/media.py`; and `func`, "
        "the plain dotted identity defined above. If source definitions ever map "
        "to the same dotted identity, combine them into one entry and sum their "
        "events. Sort entries by `func` ascending by Unicode code-point order, "
        "breaking any tie by `file` ascending in the same order. Do not include "
        "line numbers, values, null placeholders, per-test subtotals, or any "
        "additional keys."
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    functions = scoped_functions(Path(TARGET_FILE))
    answer = invocation_counts(Path(args.trace_log), functions)
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": question_text(),
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}]
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
