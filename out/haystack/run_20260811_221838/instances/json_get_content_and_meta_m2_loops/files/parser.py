import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = Path("haystack/components/converters/json.py")
TARGET_FUNC = "haystack.components.converters.json._get_content_and_meta"

QUESTION = """Run every test method in class `TestJSONConverterLoopDynamics` from `haystack_qa/json_get_content_and_meta_m2_loops/files/testcase.py` and aggregate the behavior across all of them. The covered methods are `test_alpha_sparse_metadata`, `test_bravo_three_sources`, `test_charlie_wide_metadata`, `test_delta_empty_metadata_set`, `test_echo_four_sources`, `test_foxtrot_dense_records`, `test_golf_single_metadata_field`, `test_hotel_broad_sources`, `test_india_larger_batches`, `test_juliet_mixed_rejections`, `test_kilo_many_metadata_fields`, and `test_lima_long_source_sequence`. Each test is identified by its full pytest id in the form `haystack_qa/json_get_content_and_meta_m2_loops/files/testcase.py::TestJSONConverterLoopDynamics::<method_name>`; execute them in pytest collection order, which is their alphabetical/source order here.

For `haystack.components.converters.json.JSONConverter._get_content_and_meta` in `haystack/components/converters/json.py`, consider the `for field in meta_fields` loop whose header is at absolute, 1-based line 237. For each invocation of the target, define that loop's iteration count as the number of times its body's first line, absolute line 238 (`meta[field] = ...`), executes in that invocation's own frame. Because this loop is nested under the loop at line 218, sum line 238 executions across every entry to the inner loop within the same invocation. An invocation in which line 238 never executes contributes an iteration count of zero; do not omit it. For example, if the body's first line executes twice in one invocation, that invocation's count is 2.

An invocation means one call of the target function made while running the listed test methods. Number invocations 1-based in chronological execution order across the complete pytest run. Count only executions in the target function's own frame, not activity in callers, callees, comprehensions, or generator resumptions, and retain duplicate per-invocation counts. Source line numbers are absolute, 1-based line numbers in the named repository file. For a multi-line statement, its executed line is the line where that statement or expression begins; decorator, `def`, and docstring lines are not loop-body iterations.

Return a JSON object with exactly two keys: `max_iterations` and `min_iterations`. Each value is a JSON integer and is respectively the numerical maximum and minimum of the per-invocation counts over all target invocations from all listed tests. Compare counts as ordinary integers; duplicates are not removed, and ties require no tie-breaker because only the extrema are returned."""


def loop_body_line(source_path: Path) -> int:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"cannot inspect target source {source_path}: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "JSONConverter":
            continue
        for member in node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if member.name != "_get_content_and_meta":
                continue
            for candidate in ast.walk(member):
                if (
                    isinstance(candidate, ast.For)
                    and isinstance(candidate.target, ast.Name)
                    and candidate.target.id == "field"
                    and isinstance(candidate.iter, ast.Name)
                    and candidate.iter.id == "meta_fields"
                    and candidate.body
                ):
                    if candidate.lineno != 237 or candidate.body[0].lineno != 238:
                        raise RuntimeError(
                            "target loop moved; question line numbers must be updated "
                            f"(found header {candidate.lineno}, body {candidate.body[0].lineno})"
                        )
                    return candidate.body[0].lineno
    raise RuntimeError("could not locate the target loop in JSONConverter._get_content_and_meta")


def parse_counts(trace_path: Path, body_line: int) -> list[int]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    event_pattern = re.compile(
        r"(?P<path>\S*haystack/components/converters/json\.py):(?P<line>\d+) "
        r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
    )
    target_events = 0
    active_count = None
    counts: list[int] = []

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = event_pattern.search(raw_line)
        if match is None or match.group("func") != TARGET_FUNC:
            continue
        target_events += 1
        event = match.group("event")
        line_number = int(match.group("line"))

        if event == "call":
            if active_count is not None:
                raise RuntimeError("overlapping target invocations found in trace")
            active_count = 0
        elif event == "line":
            if active_count is None:
                raise RuntimeError("target line event found outside an invocation")
            if line_number == body_line:
                active_count += 1
        elif event == "return":
            if active_count is None:
                raise RuntimeError("target return event found without a matching call")
            counts.append(active_count)
            active_count = None

    if target_events == 0:
        raise RuntimeError(f"trace contains zero events for {TARGET_FUNC}")
    if active_count is not None:
        raise RuntimeError("trace ended during an active target invocation")
    if not counts:
        raise RuntimeError(f"trace contains no complete invocations of {TARGET_FUNC}")
    return counts


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    try:
        body_line = loop_body_line(TARGET_FILE)
        counts = parse_counts(args.trace_log, body_line)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    oracle = {
        "question_kind": "M2_Loops",
        "question": QUESTION,
        "template_answer": {"max_iterations": "int", "min_iterations": "int"},
        "oracle_answer": {
            "max_iterations": max(counts),
            "min_iterations": min(counts),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
