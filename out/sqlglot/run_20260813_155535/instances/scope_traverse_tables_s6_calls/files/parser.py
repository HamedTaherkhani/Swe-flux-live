import argparse
import json
from pathlib import Path
import re


TARGET_FILE = "sqlglot/optimizer/scope.py"
TARGET_FUNC = "sqlglot.optimizer.scope._traverse_tables"
TRACKED_FUNCS = {
    "sqlglot.optimizer.scope.Scope.branch",
    "sqlglot.optimizer.scope._get_source_alias",
    "sqlglot.optimizer.scope._is_derived_table",
    "sqlglot.optimizer.scope._traverse_ctes",
    "sqlglot.optimizer.scope._traverse_scope",
    "sqlglot.optimizer.scope._traverse_select",
    "sqlglot.optimizer.scope._traverse_subqueries",
    "sqlglot.optimizer.scope._traverse_tables",
    "sqlglot.optimizer.scope._traverse_udtfs",
    "sqlglot.optimizer.scope._traverse_union",
    "sqlglot.optimizer.scope.traverse_scope",
}
EVENT_RE = re.compile(
    r" (?P<path>/\S*sqlglot/optimizer/scope\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run the single pytest test "
    "`sqlglot_qa/scope_traverse_tables_s6_calls/files/testcase.py::"
    "TestScopeCallBehavior::test_generated_nested_relations`. Over the complete execution "
    "of that test method, what is the chronological sequence of Python `call` trace events "
    "for exactly these functions from `sqlglot/optimizer/scope.py`: "
    "`sqlglot.optimizer.scope.traverse_scope`, "
    "`sqlglot.optimizer.scope._traverse_scope`, "
    "`sqlglot.optimizer.scope._traverse_select`, "
    "`sqlglot.optimizer.scope._traverse_ctes`, "
    "`sqlglot.optimizer.scope._traverse_tables`, "
    "`sqlglot.optimizer.scope._traverse_subqueries`, "
    "`sqlglot.optimizer.scope._traverse_union`, "
    "`sqlglot.optimizer.scope._traverse_udtfs`, "
    "`sqlglot.optimizer.scope._is_derived_table`, "
    "`sqlglot.optimizer.scope.Scope.branch`, and "
    "`sqlglot.optimizer.scope._get_source_alias`? The primary target is "
    "`sqlglot.optimizer.scope._traverse_tables` in `sqlglot/optimizer/scope.py`. "
    "Function identity is the fully qualified dotted form `module.qualname`; for example, "
    "a method could be written as `sample.worker.Job.run`. Include a call whenever a "
    "Python `call` trace event for one of the exact functions listed above occurs while "
    "the test method is executing, including nested and transitive calls; the call need "
    "not be made directly by the target frame and the target need not be on the stack. "
    "Exclude all functions not in the exact list, including builtins and comprehension "
    "frames. An invocation means one such `call` event and invocations are numbered "
    "1-based in chronological event order. Under Python tracing semantics, a generator "
    "produces a `call` event both on initial entry and on every resumption after a yield; "
    "include each of those events as a separate repeated entry. Retain every duplicate "
    "and preserve event order; do not sort or deduplicate. For each event, emit `file` as "
    "the forward-slash, repository-relative path and `func` in the dotted format just "
    "defined. Return exactly a JSON object with key `function_call_order`, whose value is "
    "a JSON array of objects with exactly the string keys `file` and `func` (in that key "
    "schema). No line numbers or values from line, return, or exception events are "
    "included."
)


def compute_call_order(trace_path: Path) -> list[dict[str, str]]:
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    target_event_count = 0
    calls = []
    seen_funcs = set()

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue

        func = match.group("func")
        event = match.group("event")
        if func == TARGET_FUNC:
            target_event_count += 1

        if event == "call" and func in TRACKED_FUNCS:
            calls.append({"file": TARGET_FILE, "func": func})
            seen_funcs.add(func)

    if target_event_count == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if not calls:
        raise RuntimeError("trace contains zero tracked call events")
    if len(seen_funcs) < 2:
        raise RuntimeError("trace contains calls for fewer than two tracked functions")

    return calls


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}],
        },
        "oracle_answer": {
            "function_call_order": compute_call_order(args.trace_log),
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
