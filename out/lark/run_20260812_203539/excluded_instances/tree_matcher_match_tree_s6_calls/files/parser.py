import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "lark/tree_matcher.py"
TARGET_FUNC = "lark.tree_matcher.TreeMatcher.match_tree"
INVOCATION = 1
TRACKED_FUNCS = {
    TARGET_FUNC,
    "lark.tree_matcher.parse_rulename",
    "lark.tree_matcher._best_rules_from_group",
    "lark.tree_matcher._best_from_group",
    "lark.tree_matcher._best_rules_from_group.<locals>.<lambda>",
    "lark.tree_matcher.TreeMatcher.match_tree.<locals>.<dictcomp>",
    "lark.tree_matcher.ChildrenLexer.__init__",
    "lark.tree_matcher.ChildrenLexer.lex",
    "lark.tree_matcher._match",
    "lark.tree_matcher._MakeTreeMatch.__call__",
}
EVENT_RE = re.compile(
    r" (?P<file>/[^ ]+):(?P<line>\d+) "
    r"(?P<func>[^ ]+) event=(?P<event>call|line|return|exception)\b"
)


QUESTION = """Run the single pytest test
`lark_qa/tree_matcher_match_tree_s6_calls/files/testcase.py::TestTreeMatcherCallStructure::test_seeded_mixed_segment_batches`
against the repository as provided. Consider the 1st invocation of
`lark.tree_matcher.TreeMatcher.match_tree` in `lark/tree_matcher.py`. An
invocation is one Python `call` event entering that function during this test,
numbered from 1 in chronological event-emission order.

Report the exact ordered sequence of Python `call` events for this tracked set:
`lark.tree_matcher.TreeMatcher.match_tree`,
`lark.tree_matcher.parse_rulename`,
`lark.tree_matcher._best_rules_from_group`,
`lark.tree_matcher._best_from_group`,
`lark.tree_matcher._best_rules_from_group.<locals>.<lambda>`,
`lark.tree_matcher.TreeMatcher.match_tree.<locals>.<dictcomp>`,
`lark.tree_matcher.ChildrenLexer.__init__`,
`lark.tree_matcher.ChildrenLexer.lex`, `lark.tree_matcher._match`, and
`lark.tree_matcher._MakeTreeMatch.__call__`. Begin with the `call` event that
enters the specified `match_tree` invocation itself. Then include every call
to a function in the tracked set that occurs while that invocation's frame
remains on the Python call stack, whether the call is direct from
`match_tree` or nested/transitive through another function. Stop at the
matching `return` event from that invocation; return, line, and exception
events are not entries.

Exclude calls before or after that interval and calls to every unlisted
function, including builtins and any unlisted comprehension frame. Retain
every repeated call without deduplication. A generator start or resumption
would count separately whenever Python emits a `call` event for it; none of
the tracked functions is a generator.

Order entries by chronological event-emission order; do not sort or
deduplicate them. If timestamps would tie, observed emission order is the
tie-breaker. For each entry, `file` is the repository-relative POSIX path and
`func` is the full dotted function identity in `module.Class.method` or
`module.function` form (for example, `lark.tree.Tree.pretty`). Nested
function components such as `<locals>` remain present exactly as shown in
the tracked set. Both values are ordinary JSON strings without `repr()`
quotes or other normalization.

Return exactly one JSON object with key `function_call_order`. Its value is a
JSON array of objects, each having exactly `file` (string) and `func` (string)
in that key order. Preserve sequence duplicates. No other keys are
permitted."""


def parse_trace(trace_path: Path):
    if not trace_path.is_file():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = []
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        absolute_file = match.group("file").replace("\\", "/")
        if not absolute_file.endswith("/" + TARGET_FILE):
            continue
        event = {
            "file": TARGET_FILE,
            "func": match.group("func"),
            "event": match.group("event"),
        }
        events.append(event)
        if event["func"] == TARGET_FUNC:
            target_events += 1

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET_FUNC}"
        )

    invocation_count = 0
    active = False
    completed = False
    sequence = []
    for event in events:
        if event["event"] == "call" and event["func"] == TARGET_FUNC:
            invocation_count += 1
            if invocation_count == INVOCATION:
                active = True

        if active and event["event"] == "call" and event["func"] in TRACKED_FUNCS:
            sequence.append({"file": event["file"], "func": event["func"]})

        if active and event["event"] == "return" and event["func"] == TARGET_FUNC:
            completed = True
            break

    if invocation_count < INVOCATION:
        raise RuntimeError(
            f"trace contains only {invocation_count} target calls; need {INVOCATION}"
        )
    if not completed:
        raise RuntimeError(f"target invocation {INVOCATION} has no matching return")
    if not sequence:
        raise RuntimeError(
            f"target invocation {INVOCATION} produced no tracked calls"
        )

    observed_funcs = {entry["func"] for entry in sequence}
    missing_funcs = sorted(TRACKED_FUNCS - observed_funcs)
    if missing_funcs:
        raise RuntimeError(
            "target invocation did not call every tracked function: "
            + ", ".join(missing_funcs)
        )
    return sequence


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    sequence = parse_trace(args.trace_log)
    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": sequence},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
