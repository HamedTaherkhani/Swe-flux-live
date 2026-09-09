from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET_FILE = "scrapy/commands/genspider.py"
TARGET_FUNC = "scrapy.commands.genspider.Command.run"
TRACKED_FUNCS = {
    TARGET_FUNC,
    "scrapy.commands.genspider.Command._find_template",
    "scrapy.commands.genspider.Command._generate_template_variables",
    "scrapy.commands.genspider.Command._genspider",
    "scrapy.commands.genspider.Command._list_templates",
    "scrapy.commands.genspider.Command._spider_exists",
    "scrapy.commands.genspider.extract_domain",
    "scrapy.commands.genspider.sanitize_module_name",
    "scrapy.commands.genspider.verify_url_scheme",
}
EVENT_RE = re.compile(
    r"(?P<file>\S*scrapy/commands/genspider\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)

QUESTION = """Run only the pytest test
`scrapy_qa/genspider_run_s6_calls/files/testcase.py::TestGenspiderRunCallStructure::test_seeded_command_modes`.
Across that complete test run, report the chronological call-event sequence
around every invocation of `scrapy.commands.genspider.Command.run` in
`scrapy/commands/genspider.py`.

An invocation means one `call` event for that exact function; invocations are
numbered from 1 in chronological order, and this question aggregates all of
them. Count exactly these nine function identities:
`scrapy.commands.genspider.Command.run`,
`scrapy.commands.genspider.Command._find_template`,
`scrapy.commands.genspider.Command._generate_template_variables`,
`scrapy.commands.genspider.Command._genspider`,
`scrapy.commands.genspider.Command._list_templates`,
`scrapy.commands.genspider.Command._spider_exists`,
`scrapy.commands.genspider.extract_domain`,
`scrapy.commands.genspider.sanitize_module_name`, and
`scrapy.commands.genspider.verify_url_scheme`.

Include the `call` event that begins each `Command.run` invocation. After it,
include a `call` event for any other exact function in the listed set whenever
that event occurs while that `Command.run` invocation remains on the call
stack, whether the call is direct or nested/transitive. Stop including events
for that invocation when its frame returns, including return caused by an
uncaught exception. Calls to every function outside the exact listed set are
ignored, including builtins, property getters, comprehension frames, and
generator frames. A listed function's repeated calls are retained. If a
listed function were a generator or coroutine, each resume that produces a
Python `call` event would be retained as another entry.

Preserve chronological `call`-event order across the whole test: do not sort
or deduplicate entries. Events in this single-threaded test have no ties.
Function identity is the fully qualified dotted form `module.qualname`, for
example `scrapy.http.Request.copy`. The `file` value is the repository-relative
POSIX path of the function's source file; for example, an absolute source path
ending in `tests/sample.py` is serialized as `tests/sample.py`.

Return exactly
`{"function_call_order": [{"file": <str>, "func": <str>}, ...]}`.
Every entry has exactly the two string-valued keys `file` and `func`; there is
no null or omitted representation. The array order is the chronology defined
above, and object key order carries no additional meaning."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def main() -> None:
    args = parse_args()
    trace_path = Path(args.trace_log)
    if not trace_path.is_file():
        fail(f"trace log does not exist: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    active_run_depth = 0
    call_order: list[dict[str, str]] = []

    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        func = match.group("func")
        event = match.group("event")

        if func == TARGET_FUNC:
            target_events += 1
            if event == "call":
                target_calls += 1
                active_run_depth += 1
                call_order.append({"file": TARGET_FILE, "func": func})
                continue
            if event == "return":
                if active_run_depth < 1:
                    fail("encountered a Command.run return without an active invocation")
                active_run_depth -= 1
                continue

        if event == "call" and active_run_depth > 0 and func in TRACKED_FUNCS:
            call_order.append({"file": TARGET_FILE, "func": func})

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls < 15:
        fail(f"expected at least 15 invocations of {TARGET_FUNC}, found {target_calls}")
    if active_run_depth != 0:
        fail(f"trace ended with {active_run_depth} active Command.run frame(s)")
    if len(call_order) < 40:
        fail(f"expected a rich call sequence, found only {len(call_order)} entries")

    payload = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": call_order},
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {out_path} with {len(call_order)} calls "
        f"across {target_calls} Command.run invocations"
    )


if __name__ == "__main__":
    main()

