import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "src/click/termui.py"
TARGET_FUNC = "click.termui.prompt"
LOOP_HEADER_LINE = 260

QUESTION = (
    "Run only the pytest test "
    "`click_qa/termui_prompt_s2_loops/files/testcase.py::"
    "TestPromptLoopBehavior::test_generated_retries_and_confirmations`. "
    "During that run, consider the first and only invocation of "
    "`click.termui.prompt` in `src/click/termui.py`. An invocation means one "
    "call of that function, counted 1-based in chronological order. For the "
    "`while` loop whose header is at absolute line 260, what is the exact "
    "number of iterations across every activation or re-entry of that same "
    "syntactic loop during this invocation? Iteration counting is 1-based: "
    "iteration N is the Nth dynamic execution of the loop body's first "
    "executable line, which is absolute line 261 (`value = "
    "prompt_func(prompt)`), and every such execution is counted. Do not count "
    "execution of the loop header itself, and do not sort or deduplicate "
    "executions. Source line numbers are absolute, 1-based line numbers in "
    "the named repository file. For a multi-line statement or expression, "
    "its line is the line where it begins; decorator, `def`, and docstring "
    "lines do not count as iterations unless they are the identified loop "
    "body line (they are not here). Return exactly one JSON object with shape "
    "`{\"loop_iteration_count\": <int>}`. The key "
    "`loop_iteration_count` has a base-10 JSON integer value, not a string; "
    "sorting and value-formatting conventions do not otherwise apply to this "
    "single scalar."
)

TRACE_LINE = re.compile(
    r"(?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def find_loop_body_line(source_path):
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read target source {source_path}: {exc}")

    tree = ast.parse(source, filename=str(source_path))
    target_defs = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "prompt"
        and node.lineno == 167
    ]
    if len(target_defs) != 1:
        fail(f"expected one target definition in {TARGET_FILE}")

    loops = [
        node
        for node in ast.walk(target_defs[0])
        if isinstance(node, ast.While) and node.lineno == LOOP_HEADER_LINE
    ]
    if len(loops) != 1 or not loops[0].body:
        fail(
            f"expected one non-empty while loop at "
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

    call_count = sum(event == "call" for _, event in target_events)
    if call_count != 1:
        fail(f"expected one target invocation, found {call_count}")

    iteration_count = sum(
        event == "line" and line_number == body_line
        for line_number, event in target_events
    )
    if iteration_count == 0:
        fail(
            f"trace contains no loop-body events at "
            f"{TARGET_FILE}:{body_line}"
        )
    return iteration_count


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    body_line = find_loop_body_line(Path.cwd() / TARGET_FILE)
    if body_line != 261:
        fail(f"loop body starts at unexpected line {body_line}")

    payload = {
        "question_kind": "S2_Loops",
        "question": QUESTION,
        "template_answer": {"loop_iteration_count": "int"},
        "oracle_answer": {
            "loop_iteration_count": parse_trace(args.trace_log, body_line)
        },
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
