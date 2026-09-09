from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path


TARGET_FILE = "scrapy/pqueues.py"
TARGET_FUNC = "scrapy.pqueues.DownloaderAwarePriorityQueue._next_slot"
TARGET_NAME = "_next_slot"
TARGET_DEF_LINE = 364

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def target_metadata(source_path: Path):
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        fail(f"cannot parse target source {source_path}: {exc}")

    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == TARGET_NAME
            and node.lineno == TARGET_DEF_LINE
        ),
        None,
    )
    if target is None or not target.body:
        fail(f"could not locate target function at {source_path}:{TARGET_DEF_LINE}")

    first_body_line = target.body[0].lineno
    last_body_line = max(
        getattr(node, "end_lineno", node.lineno) for node in target.body
    )
    statements = [
        node
        for node in ast.walk(target)
        if isinstance(node, ast.stmt) and node is not target
    ]
    statement_starts = {node.lineno for node in statements}

    def normalize(line: int) -> int:
        if line in statement_starts:
            return line
        enclosing = [
            node
            for node in statements
            if node.lineno < line <= getattr(node, "end_lineno", node.lineno)
        ]
        if not enclosing:
            return line
        innermost = min(
            enclosing,
            key=lambda node: (
                getattr(node, "end_lineno", node.lineno) - node.lineno,
                -node.lineno,
            ),
        )
        return innermost.lineno

    return first_body_line, last_body_line, normalize


def parse_target_events(trace_path: Path):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                {
                    "event": match.group("event"),
                    "line": int(match.group("line")),
                    "path": Path(match.group("file")),
                }
            )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not any(event["event"] == "line" for event in events):
        fail(f"trace contains zero line events for {TARGET_FUNC}")
    return events


def build_answer(events):
    source_paths = sorted(
        {event["path"].resolve() for event in events},
        key=lambda path: path.as_posix(),
    )
    if len(source_paths) != 1:
        fail(f"target events refer to {len(source_paths)} source paths, expected one")

    first_line, last_line, normalize = target_metadata(source_paths[0])
    counts: Counter[int] = Counter()
    for event in events:
        if event["event"] != "line":
            continue
        normalized_line = normalize(event["line"])
        if first_line <= normalized_line <= last_line:
            counts[normalized_line] += 1

    if not counts:
        fail("no target line events remained after body-range filtering")

    return {
        "line_execution_counts": [
            {"count": counts[line], "line": line}
            for line in range(first_line, last_line + 1)
        ]
    }


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    answer = build_answer(parse_target_events(Path(args.trace_log)))
    question = (
        "Run every pytest test method in "
        "`scrapy_qa/pqueues_next_slot_m1_cfg/files/testcase.py::"
        "PriorityQueueSelectionTest`. The covered methods are "
        "`test_rotating_dense_ties`, `test_sparse_scores_with_peeks`, "
        "`test_reverse_lexical_pressure`, `test_prime_stride_rotation`, "
        "`test_many_equal_minima`, `test_wide_score_distribution`, "
        "`test_smallest_supported_volume`, `test_even_slot_permutation`, "
        "`test_clustered_active_counts`, `test_longer_selection_history`, "
        "`test_coprime_slot_walk`, and `test_high_tie_turnover`; each full pytest "
        "id is the file-and-class id above followed by `::<method_name>`. "
        "Aggregate the results over all invocations made by all of those methods. "
        "For `scrapy.pqueues.DownloaderAwarePriorityQueue._next_slot` in "
        "`scrapy/pqueues.py`, report the total execution count for every physical "
        "source line in its body, namely every absolute 1-based line from 365 "
        "through 389 inclusive. Count only CPython runtime `line` events whose "
        "frame is exactly that fully qualified function; exclude events in callers, "
        "callees, comprehensions, or any other frame, and exclude `call`, `return`, "
        "and `exception` events. Every occurrence counts, across every invocation; "
        "do not deduplicate repeated events. For a multi-line statement or "
        "expression, attribute an event reported on a continuation line to the "
        "absolute 1-based line where its innermost enclosing Python AST statement "
        "begins. For example, an event on an argument continuation of a multi-line "
        "`return make_value(...)` counts at the `return` statement's first line. "
        "A clause represented by its own AST statement, such as an `elif`, retains "
        "its own starting line. Include all physical lines in the stated body range: "
        "a blank line, comment-only line, continuation line, or any executable line "
        "that receives no event after that normalization must still appear with "
        "count 0. The `def` line 364 and any decorator lines are outside the body "
        "range and must not appear; there is no docstring line in this function. "
        "Method execution order and invocation order do not affect these totals. "
        "Return exactly one JSON object with key `line_execution_counts`. Its value "
        "must be a JSON array containing exactly one object for each line in the "
        "inclusive range, sorted by `line` ascending with no omitted or duplicate "
        "line entries. Each element has exactly two keys: `count` and `line`, both "
        "JSON integers (not strings); `line` is the absolute 1-based source line and "
        "`count` is the aggregated event total, using 0 for no event. No local "
        "values or Python `repr`/`str` strings are part of the answer."
    )

    payload = {
        "question_kind": "M1_IntraProceduralCFG",
        "question": question,
        "template_answer": {
            "line_execution_counts": [{"count": "int", "line": "int"}]
        },
        "oracle_answer": answer,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote oracle to {out_path}")


if __name__ == "__main__":
    main()
