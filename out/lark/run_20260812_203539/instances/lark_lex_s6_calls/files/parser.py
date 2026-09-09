#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path


QUESTION = """Run the pytest test `lark_qa/lark_lex_s6_calls/files/testcase.py::TestLarkLexCallFlow::test_programmatic_lexing_modes` and report the ordered call-event sequence for the tracked functions `lark.lark.Lark.lex` and `lark.lark.Lark._build_lexer`. The primary target is `lark.lark.Lark.lex` in `lark/lark.py`.

A function identity is its Python dotted name in `module.Class.method` or `module.function` form; for example, `lark.tree.Tree.pretty`. An invocation is one Python `call` event for that function during the test method, and invocations are numbered 1-based in chronological event order. Start with the first tracked call event that occurs after the named test method begins and stop when that method returns. Append a record immediately for every `call` event whose function identity is exactly one of the two tracked identities above, whether the call is made directly by the test, directly by `Lark.lex`, or transitively while another call is active. Preserve repeated calls and do not deduplicate. Calls to every other function are omitted, including builtins, comprehension frames, and methods such as a postlexer's `process`. Neither return, line, nor exception events count. If a tracked function were a generator, each entry or resumption that produces a Python `call` event would count as a separate record.

Return one JSON object with exactly the key `function_call_order`. Its value is a list in the chronological append order just defined; there is no secondary sorting or deduplication. Each element has exactly `file` and `func`, both JSON strings. `file` is the repository-relative POSIX path of the function's defining file (not the test's file), and `func` is the dotted identity defined above. For example, a hypothetical function defined in `pkg/sample.py` could be represented as `{"file": "pkg/sample.py", "func": "pkg.sample.Work.run"}`."""

TRACKED = {
    "lark.lark.Lark.lex",
    "lark.lark.Lark._build_lexer",
}
TARGET = "lark.lark.Lark.lex"
EVENT_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    r"(?P<func>\S+)\s+event=(?P<event>call|line|return|exception)\b"
)


def parse_call_order(trace_path: Path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    text = trace_path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = []
    target_events = 0
    for raw_line in text.splitlines():
        match = EVENT_RE.search(raw_line)
        if not match:
            continue
        func = match.group("func")
        if func == TARGET:
            target_events += 1
        if match.group("event") != "call" or func not in TRACKED:
            continue

        absolute_file = match.group("file").replace("\\", "/")
        marker = "/lark/lark.py"
        if not absolute_file.endswith(marker):
            raise RuntimeError(
                f"tracked call has unexpected defining file: {absolute_file}"
            )
        events.append({"file": marker.lstrip("/"), "func": func})

    if target_events == 0:
        raise RuntimeError(
            f"trace contains zero events for target function {TARGET}"
        )
    if not events:
        raise RuntimeError("trace contains no tracked call events")
    if not any(event["func"] == TARGET for event in events):
        raise RuntimeError(f"trace contains no call event for target {TARGET}")
    if len({event["func"] for event in events}) < len(TRACKED):
        missing = sorted(TRACKED - {event["func"] for event in events})
        raise RuntimeError(f"trace is missing tracked function calls: {missing}")
    return events


def main():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    oracle = {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "function_call_order": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": {"function_call_order": parse_call_order(args.trace_log)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(oracle, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(oracle, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
