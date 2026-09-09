import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/click/testing.py"
TARGET_FUNC = "click.testing.CliRunner.isolation"
LOOP_HEADER_LINE = 577

QUESTION = (
    "Run only the pytest test "
    "`click_qa/testing_isolation_s2_loops/files/testcase.py::"
    "TestIsolationLoopBehavior::test_generated_environment_round_trip`. "
    "During that run, consider the first and only invocation of "
    "`click.testing.CliRunner.isolation` in `src/click/testing.py`. "
    "Here, an invocation is one call of the decorated method that begins one "
    "execution of its underlying generator body, counted 1-based in "
    "chronological order; suspending and resuming that generator remains part "
    "of the same invocation. For the `for` loop whose header is at line 577, "
    "what is its exact iteration count? Source line numbers are absolute, "
    "1-based line numbers in the named repository file; for a multi-line "
    "statement, the line is where that statement or expression begins. "
    "Iteration counting is 1-based, and iteration N is the Nth dynamic "
    "execution of the loop body's first executable line (line 578, "
    "`if value is None:`). Count every such execution in that invocation, "
    "without sorting or deduplicating executions. Return exactly one JSON "
    "object with the key `loop_iteration_count`; its value must be a base-10 "
    "JSON integer (not a string), with shape "
    "`{\"loop_iteration_count\": <int>}`."
)

TRACE_LINE = re.compile(
    r"(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def loop_body_first_line(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")

    tree = ast.parse(source, filename=str(source_path))
    loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.For, ast.While))
        and node.lineno == LOOP_HEADER_LINE
    ]
    if len(loops) != 1 or not loops[0].body:
        fail(
            f"expected exactly one non-empty loop at "
            f"{TARGET_FILE}:{LOOP_HEADER_LINE}"
        )
    return loops[0].body[0].lineno


def parse_trace(trace_path, body_line):
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_LINE.search(raw_line)
        if match is None:
            continue
        normalized_file = match.group("file").replace("\\", "/")
        if not normalized_file.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue
        target_events.append(
            (int(match.group("line")), match.group("event"))
        )

    if not target_events:
        fail(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )

    count = sum(
        1
        for line_number, event in target_events
        if event == "line" and line_number == body_line
    )
    if count == 0:
        fail(
            f"trace contains no loop-body line events at "
            f"{TARGET_FILE}:{body_line}"
        )
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    repository_root = Path.cwd()
    body_line = loop_body_first_line(repository_root / TARGET_FILE)
    if body_line != 578:
        fail(
            f"loop body starts at unexpected line {body_line}; expected 578"
        )

    iteration_count = parse_trace(args.trace_log, body_line)
    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {"loop_iteration_count": iteration_count},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, SyntaxError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
