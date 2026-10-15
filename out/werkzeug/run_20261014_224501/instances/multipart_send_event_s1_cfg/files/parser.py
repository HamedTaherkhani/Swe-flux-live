#!/usr/bin/env python
"""Parse the MultipartEncoder.send_event trace into the S1_IntraProceduralCFG oracle."""
import argparse
import json
import re
import sys

TARGET_FUNC = "werkzeug.sansio.multipart.MultipartEncoder.send_event"
TARGET_FILE = "src/werkzeug/sansio/multipart.py"
INVOCATION_K = 8

LINE_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = (
    "Consider the pytest test "
    "`werkzeug_qa/multipart_send_event_s1_cfg/files/testcase.py::TestMultipartEncoderScript::test_encode_scripted_stream` "
    "(test file `werkzeug_qa/multipart_send_event_s1_cfg/files/testcase.py`, class `TestMultipartEncoderScript`, "
    "single test method `test_encode_scripted_stream`). The test builds a seeded event script with `build_script` "
    "and feeds every event, in order, to `MultipartEncoder.send_event` "
    "(qualname `werkzeug.sansio.multipart.MultipartEncoder.send_event`, defined in `src/werkzeug/sansio/multipart.py`). "
    "Invocations of `send_event` are counted 1-based in chronological order of their calls during the test run; "
    "every call counts, including calls that end by raising `ValueError`. "
    "For the 8th invocation, give the exact ordered sequence of executed source lines inside `send_event`'s own frame, "
    "i.e. exactly the sequence of `line` events that Python's `sys.settrace` (CPython 3.11, as installed in this "
    "repository's environment) reports for that frame, from the call until the frame returns. Rules: "
    "(1) the `def send_event` line itself is NOT included (the call event is not a line event), and there are no "
    "decorator or docstring lines; (2) lines executed in other frames (callees such as `Headers.__iter__`, "
    "`str.lower`, `t.cast`) are NOT included; (3) every line event is listed, including repeats - when a line "
    "executes again (e.g. a `for` header line re-checked on each iteration and once more when the loop is "
    "exhausted) it appears again, and nothing is deduplicated; (4) a multi-line statement is normally reported at the "
    "line where the statement begins, BUT note that `send_event` contains a multi-line `elif` condition whose set "
    "display spans several physical lines - for that condition, report whatever line events the interpreter actually "
    "emits (this may include the continuation lines holding the set elements, and the `elif` line may be reported "
    "again after them), in emission order; (5) line numbers are absolute, 1-based line numbers in "
    "`src/werkzeug/sansio/multipart.py` as checked out in the repository. "
    "Answer with `{\"executed_path\": [{\"file\": <str>, \"func\": <str>, \"line\": <int>}, ...]}` where the list is "
    "in execution order, `file` is always the repo-relative path `src/werkzeug/sansio/multipart.py` and `func` is "
    "always the dotted qualname `werkzeug.sansio.multipart.MultipartEncoder.send_event` (both repeated in every "
    "element), and `line` is a JSON integer."
)

TEMPLATE = {"executed_path": [{"file": "str", "func": "str", "line": "int"}]}


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    try:
        with open(args.trace_log, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except FileNotFoundError:
        fail(f"trace log missing: {args.trace_log}")
    if not raw:
        fail("trace log is empty")

    events = []
    for line in raw:
        m = LINE_RE.match(line)
        if not m:
            continue
        if not m.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        func = m.group("func")
        if func.startswith("src."):
            func = func[len("src."):]
        if func != TARGET_FUNC:
            continue
        events.append((m.group("event"), int(m.group("lineno"))))
    if not events:
        fail("no trace events for the target function")

    # Function is not a generator and is never re-entered, so call/return pair up sequentially.
    invocations = []
    current = None
    for ev, lineno in events:
        if ev == "call":
            if current is not None:
                fail("nested/unterminated invocation detected")
            current = []
        elif ev == "line":
            if current is None:
                fail("line event outside invocation")
            current.append(lineno)
        elif ev == "return":
            if current is None:
                fail("return event outside invocation")
            invocations.append(current)
            current = None
    if current is not None:
        fail("trace ended inside an invocation")
    if len(invocations) < INVOCATION_K:
        fail(f"only {len(invocations)} invocations traced, need {INVOCATION_K}")

    path = invocations[INVOCATION_K - 1]
    if not path:
        fail("selected invocation has no line events")
    answer = {
        "executed_path": [
            {"file": TARGET_FILE, "func": TARGET_FUNC, "line": ln} for ln in path
        ]
    }
    oracle = {
        "question_kind": "S1_IntraProceduralCFG",
        "question": QUESTION,
        "template_answer": TEMPLATE,
        "oracle_answer": answer,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(oracle, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"invocations={len(invocations)} path_len={len(path)}")
    print(json.dumps([e["line"] for e in answer["executed_path"]]))


if __name__ == "__main__":
    main()
