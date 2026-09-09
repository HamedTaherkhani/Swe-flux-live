import argparse
from collections import Counter
import json
from pathlib import Path
import re
import types


TARGET_FILE = "sqlglot/optimizer/merge_subqueries.py"
TARGET_FUNC = "sqlglot.optimizer.merge_subqueries.merge_ctes"
MODULE = "sqlglot.optimizer.merge_subqueries"
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/optimizer/merge_subqueries\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run the pytest class selector "
    "`sqlglot_qa/merge_subqueries_merge_ctes_m6_calls/files/testcase.py::"
    "TestMergeCtesInvocationCounts`, so that every method in that class whose name starts "
    "with `test_` is run exactly once. Aggregate the result across all of those test "
    "methods, rather than reporting per-method counts. The primary target called directly "
    "by the tests is `sqlglot.optimizer.merge_subqueries.merge_ctes` in "
    "`sqlglot/optimizer/merge_subqueries.py`. Consider every executable Python function "
    "code object lexically defined in that file: include module-level functions, methods, "
    "property accessors, `__init__` and other dunder methods, nested functions and closures, "
    "list/set/dict comprehensions, and generator expressions. Exclude the module body code "
    "object itself, imported callables, and inherited methods not lexically defined in the "
    "file. (The file currently has no class definitions, but the inclusion rule is stated "
    "to make the scope exact.) "
    "For each in-scope code object, report its total invocation count over the complete "
    "class run. One invocation is one Python `call` tracing event for that code object's "
    "frame, regardless of which frame caused it: include direct, transitive, recursive, "
    "and otherwise nested calls. Under Python tracing semantics, initial entry to a "
    "generator or coroutine and every resumption after a yield each emit another `call` "
    "event, so each such event counts as a separate invocation. A comprehension execution "
    "also uses its own in-scope code object and its `call` event counts. Ignore `line`, "
    "`return`, and `exception` events. "
    "Function identity is `module.co_qualname`, using each code object's dotted lexical "
    "qualified name exactly as Python records it; for example, a comprehension nested in "
    "a function could be `sample.worker.build.<locals>.<listcomp>`. Emit `file` as the "
    "forward-slash repository-relative path `sqlglot/optimizer/merge_subqueries.py`, "
    "`func` as that identity string, and `count` as a JSON integer. Include exactly one "
    "entry for every distinct in-scope identity; if multiple lexical code objects have the "
    "same `module.co_qualname` (such as two generator expressions in one function), sum "
    "their events into that identity's count. If an identity never executes in any method, "
    "include it with `count: 0`. Do not merge different code objects, remove zero-count "
    "entries, or include any callable outside the located scope, except for the explicitly "
    "stated aggregation of code objects sharing an identity. "
    "Return exactly a JSON object with key `invocation_counts`. Its value is an array of "
    "objects having exactly the keys `count`, `file`, and `func` with types integer, "
    "string, and string respectively. Sort entries by `func` ascending using ordinary "
    "Unicode string ordering, with `file` ascending as the tie-breaker if two entries have "
    "the same `func`; no further tie is possible because there is one entry per identity."
)


def code_qualnames(source_path: Path) -> set[str]:
    source = source_path.read_text(encoding="utf-8")
    root = compile(source, str(source_path), "exec")
    qualnames = set()

    def visit(code):
        for constant in code.co_consts:
            if isinstance(constant, types.CodeType):
                qualnames.add(f"{MODULE}.{constant.co_qualname}")
                visit(constant)

    visit(root)
    if not qualnames:
        raise RuntimeError(f"no function code objects found in {source_path}")
    return qualnames


def compute_counts(trace_path: Path) -> list[dict[str, object]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = []
    source_path = None
    target_event_count = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        source_path = Path(match.group("path"))
        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_event_count += 1
        events.append((func, event))

    if target_event_count == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if source_path is None or not source_path.is_file():
        raise RuntimeError("target source path could not be recovered from the trace")

    tracked = code_qualnames(source_path)
    counts = Counter(func for func, event in events if event == "call" and func in tracked)
    if not counts:
        raise RuntimeError("trace contains zero in-scope call events")
    if len(counts) < 4:
        raise RuntimeError("trace contains calls for fewer than four in-scope code objects")

    return sorted(
        (
            {"count": counts[func], "file": TARGET_FILE, "func": func}
            for func in tracked
        ),
        key=lambda item: (item["func"], item["file"]),
    )


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "invocation_counts": [{"count": "int", "file": "str", "func": "str"}],
        },
        "oracle_answer": {
            "invocation_counts": compute_counts(args.trace_log),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
