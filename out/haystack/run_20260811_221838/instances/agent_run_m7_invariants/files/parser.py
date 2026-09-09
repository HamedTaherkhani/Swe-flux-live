from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FUNC = "haystack.components.agents.agent.Agent.run"
PREDICATES = {
    "any(msg.tool_call for msg in llm_messages)": 513,
    "exe_context.component_visits['chat_generator'] - exe_context.component_visits['tool_invoker'] == 1": 513,
    "exe_context.counter < 13": 513,
    "exe_context.counter % 2 == len(llm_messages) % 2": 513,
    "exe_context.counter % 3 == 0": 498,
    "len(llm_messages) == 1": 513,
}

QUESTION = """Run every test method in the unittest class `TestAgentRunInvariants` from
`haystack_qa/agent_run_m7_invariants/files/testcase.py` using pytest. The answer
aggregates all 12 methods collected under the pytest class id
`haystack_qa/agent_run_m7_invariants/files/testcase.py::TestAgentRunInvariants`;
no method is omitted. Method execution order is pytest's collection order, but
the requested aggregate counts are independent of that order.

For `haystack.components.agents.agent.Agent.run` in
`haystack/components/agents/agent.py`, evaluate these candidate predicates
verbatim:

1. `any(msg.tool_call for msg in llm_messages)`
2. `exe_context.component_visits['chat_generator'] - exe_context.component_visits['tool_invoker'] == 1`
3. `exe_context.counter < 13`
4. `exe_context.counter % 2 == len(llm_messages) % 2`
5. `exe_context.counter % 3 == 0`
6. `len(llm_messages) == 1`

Predicates 1, 2, 3, 4, and 6 are evaluated at every execution of the line event
for absolute 1-based line 513 in the named target file, immediately before the
`if` expression beginning on that line is evaluated. Predicate 5 is evaluated
at every execution of the line event for absolute 1-based line 498,
immediately before the assignment beginning on that line is evaluated. Python
line events for a multi-line statement belong to the absolute source line
where the executed statement or expression begins; decorator, `def`, and
docstring lines are not observation points here. Evaluate each predicate using
the actual Python local values in that invocation's `Agent.run` frame at that
instant.

An invocation means one call event for `Agent.run` during the complete class
run, numbered 1-based in chronological order. Every qualifying line event in
every invocation is a separate observation: retain repeated equal states and
do not deduplicate events. `observations` is the total number of evaluations
of that predicate across all 12 test methods. `violations` is the number whose
Python truth value is false. `held_always` is exactly `violations == 0`, except
that a predicate with no observations must be reported as
`{"observations": 0, "violations": 0, "held_always": false}`.

Return exactly
`{"invariant_report": [{"held_always": bool, "observations": int, "predicate": str, "violations": int}]}`
with one object per candidate. The `predicate` value is the verbatim expression
shown above, without backticks. Sort objects by the complete `predicate`
string in ascending Unicode code-point order. Predicate strings are unique, so
no tie can occur; if they were equal, preserve the numbered order above as the
tie-break. JSON booleans are used for `held_always`; counts are JSON integers.
No runtime value is stringified or otherwise serialized in the answer."""


LINE_RE = re.compile(
    r"agent\.py:(?P<line>\d+)\s+"
    r"haystack\.components\.agents\.agent\.run\s+"
    r"event=(?P<event>\w+).*locals=(?P<locals>\{.*\})$"
)
COUNTER_RE = re.compile(r"\bcounter=(\d+)")
VISITS_RE = re.compile(
    r"component_visits=\{'chat_generator':\s*(\d+),\s*'tool_invoker':\s*(\d+)\}"
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def parse_changed_locals(raw: str, line_number: int) -> dict[str, str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        fail(f"could not parse locals on trace line {line_number}: {exc}")
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        fail(f"unexpected locals representation on trace line {line_number}")
    return value


def context_values(context_repr: str, line_number: int) -> tuple[int, int, int]:
    counter_match = COUNTER_RE.search(context_repr)
    visits_match = VISITS_RE.search(context_repr)
    if counter_match is None or visits_match is None:
        fail(f"missing execution-context fields at trace line {line_number}")
    return (
        int(counter_match.group(1)),
        int(visits_match.group(1)),
        int(visits_match.group(2)),
    )


def evaluate(predicate: str, locals_state: dict[str, str], line_number: int) -> bool:
    context_repr = locals_state.get("exe_context")
    if context_repr is None:
        fail(f"missing exe_context at trace line {line_number}")
    counter, chat_visits, tool_visits = context_values(context_repr, line_number)

    if predicate == "exe_context.counter % 3 == 0":
        return counter % 3 == 0

    messages_repr = locals_state.get("llm_messages")
    if messages_repr is None:
        fail(f"missing llm_messages at trace line {line_number}")
    message_count = messages_repr.count("ChatMessage(")
    if message_count == 0:
        fail(f"could not identify any llm_messages at trace line {line_number}")

    if predicate == "any(msg.tool_call for msg in llm_messages)":
        return "ToolCall(" in messages_repr
    if predicate == "exe_context.component_visits['chat_generator'] - exe_context.component_visits['tool_invoker'] == 1":
        return chat_visits - tool_visits == 1
    if predicate == "exe_context.counter < 13":
        return counter < 13
    if predicate == "exe_context.counter % 2 == len(llm_messages) % 2":
        return counter % 2 == message_count % 2
    if predicate == "len(llm_messages) == 1":
        return message_count == 1
    fail(f"unknown predicate: {predicate}")


def build_answer(trace_path: Path) -> dict[str, object]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    records = {predicate: {"observations": 0, "violations": 0} for predicate in PREDICATES}
    locals_state: dict[str, str] = {}
    target_events = 0

    for trace_line_number, raw_line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = LINE_RE.search(raw_line)
        if match is None:
            continue
        target_events += 1
        event = match.group("event")
        if event == "call":
            locals_state = {}
        locals_state.update(parse_changed_locals(match.group("locals"), trace_line_number))
        source_line = int(match.group("line"))

        for predicate, observation_line in PREDICATES.items():
            if event != "line" or source_line != observation_line:
                continue
            records[predicate]["observations"] += 1
            if not evaluate(predicate, locals_state, trace_line_number):
                records[predicate]["violations"] += 1

        if event == "return":
            locals_state = {}

    if target_events == 0:
        fail(f"trace log contains zero events for {TARGET_FUNC}")

    report = []
    for predicate in sorted(PREDICATES):
        observations = records[predicate]["observations"]
        violations = records[predicate]["violations"]
        report.append(
            {
                "held_always": observations > 0 and violations == 0,
                "observations": observations,
                "predicate": predicate,
                "violations": violations,
            }
        )
    return {"invariant_report": report}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    payload = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "invariant_report": [
                {
                    "held_always": "bool",
                    "observations": "int",
                    "predicate": "str",
                    "violations": "int",
                }
            ]
        },
        "oracle_answer": build_answer(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
