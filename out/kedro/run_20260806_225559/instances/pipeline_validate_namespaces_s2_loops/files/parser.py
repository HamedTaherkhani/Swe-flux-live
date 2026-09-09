import argparse
import json
import re
from pathlib import Path


TARGET_FUNC = "kedro.pipeline.pipeline._validate_namespaces"
LOOP_BODY_LINE = 354
EVENT_RE = re.compile(
    r" (?P<file>\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run the pytest test "
    "`kedro_qa/pipeline_validate_namespaces_s2_loops/files/testcase.py::"
    "TestPipelineValidateNamespacesLoops::test_accumulated_namespace_state`. "
    "During that test, consider the first invocation of "
    "`kedro.pipeline.pipeline.Pipeline._validate_namespaces` in "
    "`kedro/pipeline/pipeline.py`. An invocation means one `call` of exactly "
    "that function, counted 1-based in chronological order during the test; "
    "calls of nested comprehension frames or other functions are not "
    "invocations. For invocation 1, how many iterations does the `for ns, "
    "nodes in seen.items()` loop whose header is at line 353 execute? Line "
    "numbers are absolute, 1-based source lines in the named repository file. "
    "An iteration means one execution, in that invocation's own function "
    "frame, of the loop body's first statement "
    "`visited[ns].update(nodes)`, which begins at line 354; evaluating the "
    "loop header, exhausting the iterator, and events in nested frames do not "
    "count as iterations. Return exactly a JSON object with the single key "
    "`loop_iteration_count`; its value must be the base-10 JSON integer count "
    "(not a quoted string). Because the answer is one scalar count, no "
    "sorting, tie-breaking, or deduplication rule applies."
)


def _read_events(trace_path: Path) -> list[tuple[int, str, str]]:
    if not trace_path.exists():
        raise SystemExit(f"ERROR: trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit(f"ERROR: trace log is empty: {trace_path}")

    events = []
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                (
                    int(match.group("line")),
                    match.group("func"),
                    match.group("event"),
                )
            )
    if not events:
        raise SystemExit(
            f"ERROR: trace contains zero events for target function {TARGET_FUNC}"
        )
    return events


def _first_invocation_iteration_count(events: list[tuple[int, str, str]]) -> int:
    try:
        call_index = next(
            index for index, (_, _, event) in enumerate(events) if event == "call"
        )
    except StopIteration as exc:
        raise SystemExit("ERROR: target trace has no call event") from exc

    count = 0
    completed = False
    for line, _, event in events[call_index + 1 :]:
        if event == "call":
            raise SystemExit(
                "ERROR: encountered another target call before invocation 1 returned"
            )
        if event == "return":
            completed = True
            break
        if event == "line" and line == LOOP_BODY_LINE:
            count += 1

    if not completed:
        raise SystemExit("ERROR: invocation 1 has no return event")
    if count == 0:
        raise SystemExit(
            "ERROR: selected loop executed zero iterations in invocation 1"
        )
    return count


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    args = argument_parser.parse_args()

    events = _read_events(Path(args.trace_log))
    count = _first_invocation_iteration_count(events)
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": count},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
