#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "src/flask/sessions.py"
TARGET_FILE_SUFFIX = f"/{TARGET_FILE}"
PRIMARY_TARGET = "flask.sessions.SecureCookieSessionInterface.save_session"
TRACKED_FUNCTIONS = {
    "flask.sessions.SecureCookieSessionInterface.get_signing_serializer",
    "flask.sessions.SecureCookieSessionInterface.open_session",
    "flask.sessions.SecureCookieSessionInterface.save_session",
    "flask.sessions.SessionInterface.get_cookie_domain",
    "flask.sessions.SessionInterface.get_cookie_httponly",
    "flask.sessions.SessionInterface.get_cookie_name",
    "flask.sessions.SessionInterface.get_cookie_partitioned",
    "flask.sessions.SessionInterface.get_cookie_path",
    "flask.sessions.SessionInterface.get_cookie_samesite",
    "flask.sessions.SessionInterface.get_cookie_secure",
    "flask.sessions.SessionInterface.get_expiration_time",
    "flask.sessions.SessionInterface.is_null_session",
    "flask.sessions.SessionInterface.make_null_session",
    "flask.sessions.SessionInterface.should_set_cookie",
    "flask.sessions._lazy_sha1",
}

EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = (
    "Run only the pytest test "
    "`flask_qa/sessions_save_session_m6_calls/files/testcase.py::"
    "TestSecureCookieSaveSessionCalls::test_generated_session_matrix`. The "
    "primary target is `flask.sessions.SecureCookieSessionInterface.save_session` "
    "in `src/flask/sessions.py`. Consider exactly this tracked function set in "
    "that same file: `flask.sessions.SecureCookieSessionInterface."
    "get_signing_serializer`, `flask.sessions.SecureCookieSessionInterface."
    "open_session`, `flask.sessions.SecureCookieSessionInterface.save_session`, "
    "`flask.sessions.SessionInterface.get_cookie_domain`, "
    "`flask.sessions.SessionInterface.get_cookie_httponly`, "
    "`flask.sessions.SessionInterface.get_cookie_name`, "
    "`flask.sessions.SessionInterface.get_cookie_partitioned`, "
    "`flask.sessions.SessionInterface.get_cookie_path`, "
    "`flask.sessions.SessionInterface.get_cookie_samesite`, "
    "`flask.sessions.SessionInterface.get_cookie_secure`, "
    "`flask.sessions.SessionInterface.get_expiration_time`, "
    "`flask.sessions.SessionInterface.is_null_session`, "
    "`flask.sessions.SessionInterface.make_null_session`, "
    "`flask.sessions.SessionInterface.should_set_cookie`, and "
    "`flask.sessions._lazy_sha1`. Which members of this set execute at least "
    "once while that test runs? A function executes when its own Python frame "
    "receives a `call` event. Count an invocation regardless of whether it is "
    "called directly by the test, directly by another listed function, or "
    "transitively through unlisted code; merely being on the stack while some "
    "other function runs does not count as an invocation. Ignore every "
    "function outside the listed set, including unlisted Python callees, "
    "implicit comprehension frames, and builtins or other C-level calls. "
    "Repeated calls and recursive calls each constitute another invocation "
    "but do not duplicate a function in the answer. If a generator or "
    "coroutine frame receives additional `call` events when it resumes, each "
    "such event is another invocation under this rule, but it likewise cannot "
    "duplicate the function in this set-valued answer. Invocation 1 means the "
    "first qualifying `call` event in chronological call-entry order, although "
    "invocation numbers and counts are not returned. Identify each function "
    "as its dotted Python module name followed by its runtime code qualname "
    "(for example, `package.submodule.Widget.run`); for inherited methods use "
    "the class in which the executed code is defined. Identify its file as "
    "the repository-relative POSIX path `src/flask/sessions.py`. Deduplicate "
    "covered functions, then sort the resulting `{file, func}` objects in "
    "ascending lexicographic order by the two-field tuple `(file, func)`, "
    "comparing Unicode code points exactly as Python sorts strings. This is a "
    "total order; after deduplication no further tie-breaker is needed. Return "
    "a JSON object with exactly one key, `covered_functions`. Its value is a "
    "JSON array of objects, each with exactly two JSON string fields, `file` "
    "then `func`; field insertion order does not alter JSON object semantics. "
    "Every array item represents one covered function. Do not use bare "
    "function names, `repr` strings, empty-string sentinels, or JSON null, and "
    "do not include uncovered tracked functions."
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", required=True)
    arg_parser.add_argument("--out", required=True)
    args = arg_parser.parse_args()

    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log is missing: {trace_path}")

    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    primary_events = 0
    primary_calls = 0
    covered: set[tuple[str, str]] = set()

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue

        file_name = match.group("file").replace("\\", "/")
        func_name = match.group("func")
        event = match.group("event")

        if file_name.endswith(TARGET_FILE_SUFFIX) and func_name == PRIMARY_TARGET:
            primary_events += 1
            if event == "call":
                primary_calls += 1

        if (
            event == "call"
            and file_name.endswith(TARGET_FILE_SUFFIX)
            and func_name in TRACKED_FUNCTIONS
        ):
            covered.add((TARGET_FILE, func_name))

    if primary_events == 0:
        fail(f"trace contains zero events for {PRIMARY_TARGET}")
    if primary_calls == 0:
        fail(f"trace contains no call event for {PRIMARY_TARGET}")
    if not covered:
        fail("no tracked functions executed")

    answer = [
        {"file": file_name, "func": func_name}
        for file_name, func_name in sorted(covered)
    ]
    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"covered_functions": answer},
    }

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
