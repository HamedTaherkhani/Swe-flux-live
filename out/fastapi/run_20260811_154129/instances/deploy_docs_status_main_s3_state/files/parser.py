import argparse
import ast
import json
from pathlib import Path
import re
import sys


TARGET_FILE = "scripts/deploy_docs_status.py"
TARGET_FUNC = "scripts.deploy_docs_status.main"
OBSERVATION_LINE = 130
OCCURRENCE = 19
VARIABLES = (
    "message",
    "links",
    "en_links",
    "langs",
    "current_lang_links",
)

QUESTION = (
    "Run only the pytest test "
    "`fastapi_qa/deploy_docs_status_main_s3_state/files/testcase.py::"
    "TestDeployDocsStatusMain::test_builds_preview_state_from_generated_files`. "
    "During that test run, consider the first invocation of "
    "`scripts.deploy_docs_status.main` in `scripts/deploy_docs_status.py`; an "
    "invocation means one call of that exact function, numbered 1-based in "
    "chronological order. Observe its local state immediately after absolute, "
    "1-based source line 130 (`message += \"\\n\"`) has completed execution for "
    "the 19th time in that invocation, after the augmented assignment has both "
    "read and written `message` and before the next source line executes. Count "
    "only completed executions of that exact line in the target function's own "
    "frame; decorator and `def` lines, unexecuted lines, and activity in called "
    "functions or comprehension/lambda frames do not count. The named line is "
    "a single-line statement; line numbers refer to the repository file as "
    "provided, and a multi-line statement elsewhere would be identified by the "
    "line on which its statement or expression begins. Report `message`, "
    "`links`, `en_links`, `langs`, and `current_lang_links`, in exactly that "
    "order, as `{\"observed_state\": [{\"value\": <string>, \"variable\": "
    "<string>}, ...]}`. Each `variable` is the local's bare name and each "
    "`value` is Python `repr()` of the complete value at the observation point. "
    "For containers, use the `repr()` of the whole container without sorting, "
    "normalizing, or deduplicating its contents, preserving their runtime order; "
    "there is one output entry per requested variable and no duplicates are "
    "removed. Thus strings retain quotes, Python spellings such as `None` and "
    "`True` are used inside the value string, and embedded newlines are actual "
    "newline characters in the JSON string after JSON decoding (escaped by the "
    "JSON serialization on disk). No requested local is absent at this point; "
    "do not use JSON null or an empty substitute."
)

EVENT_RE = re.compile(
    r"(?P<file>\S*scripts/deploy_docs_status\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)"
    r".* locals=(?P<locals>\{.*\})$"
)


def fail(message):
    raise RuntimeError(message)


def read_target_events(trace_path):
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    events = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        match = EVENT_RE.search(raw_line)
        if not match or match.group("func") != TARGET_FUNC:
            continue
        try:
            changed = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as error:
            fail(f"cannot parse locals on trace line {line_number}: {error}")
        if not isinstance(changed, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in changed.items()
        ):
            fail(f"invalid locals payload on trace line {line_number}")
        events.append(
            {
                "event": match.group("event"),
                "line": int(match.group("line")),
                "locals": changed,
            }
        )
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    return events


def first_invocation(events):
    invocation = []
    active = False
    calls = 0
    for event in events:
        if event["event"] == "call":
            calls += 1
            if calls == 1:
                active = True
        if active:
            invocation.append(event)
            if event["event"] == "return":
                break
    if not invocation or invocation[0]["event"] != "call":
        fail(f"no invocation found for {TARGET_FUNC}")
    if invocation[-1]["event"] != "return":
        fail(f"first invocation of {TARGET_FUNC} has no return event")
    return invocation


def observed_state(invocation):
    state = {}
    completed_line_pending = False
    occurrences = 0
    snapshot = None

    for event in invocation:
        if completed_line_pending:
            state.update(event["locals"])
            snapshot = dict(state)
            break

        state.update(event["locals"])
        if event["event"] == "line" and event["line"] == OBSERVATION_LINE:
            occurrences += 1
            if occurrences == OCCURRENCE:
                completed_line_pending = True

    if snapshot is None:
        fail(
            f"line {OBSERVATION_LINE} did not complete for occurrence "
            f"{OCCURRENCE}"
        )
    if "..." in snapshot:
        fail("traced locals were truncated")
    missing = [name for name in VARIABLES if name not in snapshot]
    if missing:
        fail(f"requested locals missing at observation point: {missing}")

    return {
        "observed_state": [
            {"value": snapshot[name], "variable": name} for name in VARIABLES
        ]
    }


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True)
    argument_parser.add_argument("--out", required=True)
    arguments = argument_parser.parse_args()

    trace_path = Path(arguments.trace_log)
    output_path = Path(arguments.out)
    answer = observed_state(first_invocation(read_target_events(trace_path)))
    payload = {
        "question_kind": "S3_ProgramState",
        "question": QUESTION,
        "template_answer": {
            "observed_state": [{"value": "str", "variable": "str"}]
        },
        "oracle_answer": answer,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
