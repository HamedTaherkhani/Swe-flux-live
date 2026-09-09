from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET = "haystack.components.agents.agent.Agent.run_async"
TARGET_FILE = "haystack/components/agents/agent.py"
TRACKED = (
    "haystack.components.agents.agent.Agent._runtime_checks",
    "haystack.components.agents.agent.Agent._initialize_fresh_execution",
    "haystack.components.agents.agent.Agent._initialize_from_snapshot",
    "haystack.components.agents.agent.Agent._create_agent_span",
    "haystack.components.agents.agent.Agent._check_chat_generator_breakpoint",
    "haystack.components.agents.agent.Agent._check_tool_invoker_breakpoint",
    "haystack.components.agents.agent.Agent._check_exit_conditions",
)
METHOD_NAMES = {name.rsplit(".", 1)[-1] for name in (TARGET, *TRACKED)}
EVENT_RE = re.compile(
    r" (?P<file>/\S+):(?P<line>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)(?: |$)"
)


QUESTION = """Run the single pytest test
`haystack_qa/agent_run_async_s6_calls/files/testcase.py::AgentRunAsyncCallOrderTest::test_programmatic_tool_cycles`
and consider the first (and only) invocation of
`haystack.components.agents.agent.Agent.run_async` in
`haystack/components/agents/agent.py`.

What is the exact chronological sequence of direct calls that this invocation
makes to functions in the following tracked set?

- `haystack.components.agents.agent.Agent._runtime_checks`
- `haystack.components.agents.agent.Agent._initialize_fresh_execution`
- `haystack.components.agents.agent.Agent._initialize_from_snapshot`
- `haystack.components.agents.agent.Agent._create_agent_span`
- `haystack.components.agents.agent.Agent._check_chat_generator_breakpoint`
- `haystack.components.agents.agent.Agent._check_tool_invoker_breakpoint`
- `haystack.components.agents.agent.Agent._check_exit_conditions`

An invocation means the initial entry into the coroutine, counted by its first
Python `call` trace event; invocations are numbered 1-based in chronological
order. Later `call` events caused only by resuming that same suspended
`Agent.run_async` coroutine are continuations of invocation 1, not new
invocations. A tracked call is counted when a Python `call` event enters one of
the seven functions listed above and its immediate logical caller is the
invocation-1 `Agent.run_async` frame. Continue counting across every suspension
and resumption of that frame until it returns normally. Calls made transitively
by a helper, calls from any other frame, calls to functions outside the tracked
set, builtins, and comprehension or generator frames are excluded. The
`Agent.run_async` entry and resume events themselves are also excluded.
Retain every repeated tracked call; do not deduplicate or sort. Ordering is the
chronological order of the qualifying `call` events, with no additional
tie-breaker needed because Python dispatches these events serially in this
single coroutine.

Return exactly
`{"function_call_order": [{"file": <str>, "func": <str>}, ...]}`.
For every element, `file` is the repository-relative POSIX path of the file
containing the entered function, and `func` is its full dotted
`module.qualname`, including the class for methods (for example,
`some_package.worker.Worker.process`). Use ordinary JSON strings, and preserve
the sequence exactly as defined above."""


def parse_event(raw_line: str) -> dict[str, object] | None:
    match = EVENT_RE.search(raw_line)
    if match is None:
        return None
    file_name = match.group("file").replace("\\", "/")
    marker = file_name.find(TARGET_FILE)
    relative_file = file_name[marker:] if marker >= 0 else file_name
    func_name = match.group("func")
    module_name, _, short_name = func_name.rpartition(".")
    if module_name == "haystack.components.agents.agent" and short_name in METHOD_NAMES:
        func_name = f"{module_name}.Agent.{short_name}"
    return {
        "file": relative_file,
        "line": int(match.group("line")),
        "func": func_name,
        "event": match.group("event"),
    }


def build_oracle(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = [event for line in trace_path.read_text(encoding="utf-8").splitlines() if (event := parse_event(line))]
    target_events = [event for event in events if event["func"] == TARGET]
    if not target_events:
        raise RuntimeError(f"trace contains zero events for target function {TARGET}")

    initial_entries = [
        index
        for index, event in enumerate(events)
        if event["func"] == TARGET and event["event"] == "call" and event["line"] == 554
    ]
    if len(initial_entries) != 1:
        raise RuntimeError(f"expected exactly one initial target entry, found {len(initial_entries)}")

    start = initial_entries[0]
    terminal_returns = [
        index
        for index, event in enumerate(events[start + 1 :], start=start + 1)
        if event["func"] == TARGET and event["event"] == "return" and event["line"] == 678
    ]
    if len(terminal_returns) != 1:
        raise RuntimeError(f"expected exactly one terminal target return, found {len(terminal_returns)}")
    end = terminal_returns[0]

    order = [
        {"file": str(event["file"]), "func": str(event["func"])}
        for event in events[start + 1 : end]
        if event["event"] == "call" and event["func"] in TRACKED
    ]
    if not order:
        raise RuntimeError("target invocation made zero calls to the tracked function set")

    seen = {item["func"] for item in order}
    expected_seen = set(TRACKED) - {"haystack.components.agents.agent.Agent._initialize_from_snapshot"}
    missing = sorted(expected_seen - seen)
    if missing:
        raise RuntimeError(f"trace did not capture expected tracked functions: {missing}")

    return {
        "question_kind": "S6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {"function_call_order": [{"file": "str", "func": "str"}]},
        "oracle_answer": {"function_call_order": order},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-log", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    oracle = build_oracle(args.trace_log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(oracle["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
