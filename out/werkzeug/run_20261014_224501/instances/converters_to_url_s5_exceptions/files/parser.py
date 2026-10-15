#!/usr/bin/env python
"""Trace -> oracle.json for converters_to_url_s5_exceptions (S5_Exceptions, template 1).

Answer: type and exact str() of the first exception that propagates out of
``FloatConverter.to_url`` during the test run.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
import sys
from pathlib import Path

TARGET_SUFFIX = "routing.converters.FloatConverter.to_url"
TARGET_FILE = "src/werkzeug/routing/converters.py"

EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>\S+):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>\w+) (?P<rest>.*)$"
)
EXC_RE = re.compile(r"^exc=(?P<name>[A-Za-z_][\w.]*): (?P<repr>.*) locals=\{.*\}$")

QUESTION = (
    "Consider the pytest test "
    "`werkzeug_qa/converters_to_url_s5_exceptions/files/testcase.py::FloatToUrlTest::test_float_to_url_stream` "
    "(file `werkzeug_qa/converters_to_url_s5_exceptions/files/testcase.py`, class `FloatToUrlTest`, "
    "single test method `test_float_to_url_stream`). The test builds a seeded list of heterogeneous values "
    "and feeds them one by one, in list order, directly to "
    "`werkzeug.routing.converters.FloatConverter.to_url` (defined in `src/werkzeug/routing/converters.py`) "
    "on a converter created with `max=1e31` (unsigned), stopping at the first value for which the call "
    "raises. An invocation is one call of `FloatConverter.to_url` during the test run, counted 1-based in "
    "chronological order. Exactly one invocation during this test does not return normally: an exception "
    "propagates out of `FloatConverter.to_url` to the test (whether it was raised by a `raise` statement of "
    "the method itself or by something the method calls). What is the type and the exact message of that "
    "exception object, as seen by the caller? Type naming convention: for built-in exceptions use the bare "
    "`type(exc).__name__` (e.g. `KeyError`, never `builtins.KeyError`); for all other exceptions use "
    "`type(exc).__module__ + '.' + type(exc).__qualname__` (e.g. `http.client.HTTPException`). The message "
    "is exactly `str(exc)`, character for character (including any quotes, spaces and punctuation inside "
    "it; no surrounding quotes added, no type prefix, no stripping). "
    'Answer as JSON: {"exception_message": <str>, "exception_type": <str>}.'
)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-log", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    path = Path(args.trace_log)
    if not path.is_file():
        fail(f"trace log missing: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        fail("trace log is empty")

    # Per-frame tracking: an exception event followed by a return event with
    # retval=None (and no further line events) means the exception escaped.
    events = []
    for raw in lines:
        m = EVENT_RE.match(raw)
        if not m:
            continue
        if TARGET_FILE not in m["file"] or not m["func"].endswith(TARGET_SUFFIX):
            continue
        events.append((m["event"], int(m["lineno"]), m["rest"]))
    if not events:
        fail("no events for FloatConverter.to_url in trace")

    n_calls = sum(1 for e in events if e[0] == "call")
    escaped = []
    pending = None
    for event, lineno, rest in events:
        if event == "call":
            pending = None
        elif event == "exception":
            em = EXC_RE.match(rest)
            if not em:
                fail(f"cannot parse exception event: {rest[:200]}")
            pending = (em["name"], em["repr"])
        elif event == "line":
            pending = None  # exception handled locally (no try in target, but be safe)
        elif event == "return":
            if pending is not None and rest.startswith("retval=None "):
                escaped.append(pending)
            pending = None

    if len(escaped) != 1:
        fail(f"expected exactly one escaping exception, found {len(escaped)}")
    name, exc_repr = escaped[0]

    # exc repr is e.g. ValueError("msg") -> parse args with ast.
    expr = ast.parse(exc_repr, mode="eval").body
    if not isinstance(expr, ast.Call) or len(expr.args) != 1:
        fail(f"unexpected exception repr: {exc_repr}")
    message = str(ast.literal_eval(expr.args[0]))

    if isinstance(getattr(builtins, name, None), type) and issubclass(
        getattr(builtins, name), BaseException
    ):
        exc_type = name
    else:
        # Non-builtin exceptions raised here are defined in the target module.
        import werkzeug.routing.converters as conv_mod

        cls = getattr(conv_mod, name, None)
        if cls is None:
            fail(f"cannot resolve exception class {name}")
        exc_type = f"{cls.__module__}.{cls.__qualname__}"

    oracle = {
        "question_kind": "S5_Exceptions",
        "question": QUESTION,
        "template_answer": {"exception_message": "str", "exception_type": "str"},
        "oracle_answer": {"exception_message": message, "exception_type": exc_type},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"invocations={n_calls} events={len(events)}")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
