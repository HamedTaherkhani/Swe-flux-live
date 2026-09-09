#!/usr/bin/env python3
import argparse
import builtins
import json
import re
from pathlib import Path


TARGET_FILE = "src/llamafactory/webui/runner.py"
TARGET_FUNC = "llamafactory.webui.runner.monitor"
WAIT_LINE = 433
HANDLER_LINE = 435
CONTINUE_LINE = 436

QUESTION = (
    "Run the complete pytest test "
    "`llama_factory_qa/runner_monitor_s5_exceptions/files/testcase.py::"
    "TestRunnerCaughtExceptions::test_seeded_wait_failures_are_retried`. During that run, consider "
    "the single `llamafactory.webui.runner.Runner.monitor` generator frame in "
    "`src/llamafactory/webui/runner.py`, reached indirectly through `Runner.run_train` and "
    "`Runner._launch` and consumed until exhaustion. Report the set of dynamic exception types "
    "caught inside that frame by the `except TimeoutExpired` handler at line 435. An exception "
    "counts as caught by this handler exactly when it is raised into the target frame by the "
    "`self.trainer.wait(2)` call whose expression begins on line 433, control enters that handler, "
    "and its `continue` statement on line 436 executes; do not include exceptions caught elsewhere "
    "or exceptions that propagate out of the target frame. These are absolute 1-based line numbers "
    "in the named repository file as it exists for the test; for a multi-line statement, use the "
    "line where the executed statement or expression begins. The function's `def` line, decorator "
    "lines, and docstring line do not count as exception sites. Exception type naming MUST use "
    "this convention: bare `type(exc).__name__` for built-in exceptions (e.g. `ValueError` — never "
    "`builtins.ValueError`), and `module.QualName` for all others (e.g. "
    "`haystack.core.errors.PipelineError`). Form the set by converting every qualifying exception "
    "to that type-name string, removing duplicate strings, and sorting the remaining strings in "
    "ascending lexicographic order by Python string ordering; there are no secondary ties after "
    "deduplication. Return exactly one JSON object with exactly the key "
    "`caught_exception_kinds`; its value must be a JSON array of JSON strings in that stated order. "
    "Do not use `repr`, truncate, or otherwise normalize the type-name strings, and use an empty "
    "JSON array—not null or an omitted key—if the set is empty."
)

EVENT_RE = re.compile(
    r"(?P<path>/\S*src/llamafactory/webui/runner\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b(?P<rest>.*)"
)
EXCEPTION_RE = re.compile(r" exc=(?P<type>[^:\s]+): .* locals=")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message):
    raise SystemExit(f"ERROR: {message}")


def read_target_events(trace_path):
    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match and match.group("func") == TARGET_FUNC:
            events.append(
                {
                    "event": match.group("event"),
                    "line": int(match.group("line")),
                    "rest": match.group("rest"),
                }
            )
    return events


def normalize_type_name(trace_type_name):
    candidate = getattr(builtins, trace_type_name, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate.__name__
    if "." in trace_type_name:
        return trace_type_name
    fail(f"non-built-in exception type is not module-qualified: {trace_type_name!r}")


def extract_answer(events):
    pending_type = None
    handler_entered = False
    caught_types = []
    wait_exception_count = 0

    for item in events:
        event = item["event"]
        line = item["line"]

        if event == "exception" and line == WAIT_LINE:
            if pending_type is not None:
                fail("encountered a second wait exception before confirming the first handler")
            match = EXCEPTION_RE.search(item["rest"])
            if not match:
                fail(f"cannot parse exception event at line {WAIT_LINE}: {item['rest']!r}")
            pending_type = match.group("type")
            handler_entered = False
            wait_exception_count += 1
            continue

        if pending_type is None:
            continue

        if event == "line" and line == HANDLER_LINE:
            handler_entered = True
        elif event == "line" and line == CONTINUE_LINE:
            if not handler_entered:
                fail(f"continue line {CONTINUE_LINE} ran without entering handler line {HANDLER_LINE}")
            caught_types.append(normalize_type_name(pending_type))
            pending_type = None
            handler_entered = False
        elif event == "return":
            fail("target frame returned before a wait exception reached the continue handler")
        elif event == "line" and line > CONTINUE_LINE:
            fail(
                f"execution advanced past handler line {HANDLER_LINE} without executing "
                f"continue line {CONTINUE_LINE}"
            )

    if pending_type is not None:
        fail("trace ended before confirming whether the final wait exception was caught")
    if wait_exception_count == 0:
        fail(f"target trace contains no exception events at wait line {WAIT_LINE}")
    if len(caught_types) != wait_exception_count:
        fail(
            f"found {wait_exception_count} wait exceptions but confirmed only "
            f"{len(caught_types)} as caught"
        )

    unique_sorted = sorted(set(caught_types))
    if not unique_sorted:
        fail("computed caught-exception set is empty")
    return {"caught_exception_kinds": unique_sorted}


def main():
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    events = read_target_events(trace_path)
    if not events:
        fail(f"trace contains zero events for {TARGET_FUNC}")

    payload = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"caught_exception_kinds": ["str"]},
        "oracle_answer": extract_answer(events),
    }
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
