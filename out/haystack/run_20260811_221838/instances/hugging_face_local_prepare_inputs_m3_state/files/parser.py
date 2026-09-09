#!/usr/bin/env python3
import argparse
import ast
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "haystack/components/generators/chat/hugging_face_local.py"
TARGET_FUNC = "haystack.components.generators.chat.hugging_face_local._prepare_inputs"
EVENT_RE = re.compile(
    r"^\S+ \S+ (?P<file>.+):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>call|line|return|exception)\b.* "
    r"locals=(?P<locals>\{.*\})$"
)

QUESTION = """Run every test method in `TestPrepareInputsProgramState` from \
`haystack_qa/hugging_face_local_prepare_inputs_m3_state/files/testcase.py` \
(that is, every pytest node whose id has the prefix \
`haystack_qa/hugging_face_local_prepare_inputs_m3_state/files/testcase.py::TestPrepareInputsProgramState::test_`). \
Execute those nodes once each in pytest's displayed collection order, without \
reordering or selectively repeating them. \
Aggregate observations from all invocations of \
`haystack.components.generators.chat.hugging_face_local.HuggingFaceLocalChatGenerator._prepare_inputs` \
in `haystack/components/generators/chat/hugging_face_local.py`.

For the exact `_prepare_inputs` frame, observe the local variable \
`generation_kwargs` at these execution checkpoints: once on function entry \
after parameters are bound; immediately before every executed source line in \
that frame; and immediately before a normal return or exception leaves that \
frame. Only include checkpoints at which `generation_kwargs` is bound. A \
source-line checkpoint occurs before the statement or expression beginning \
on that absolute, 1-based line executes; for a multi-line statement, this is \
the line on which its executed statement or expression begins. Decorator and \
`def` lines are not checkpoints, and the function's non-executed docstring \
lines are not checkpoints. Exclude nested frames, including the list \
comprehension used to construct `hf_messages`; parameters in the exact frame \
are ordinary locals, while comprehension-local variables are therefore never \
observed. An invocation means one chronological entry into the exact target \
function, numbered from 1 across the complete pytest run, although invocation \
numbers are not emitted.

At each included checkpoint, take Python `repr()` of the entire current \
`generation_kwargs` object, not `str()` and not a JSON conversion. Thus values \
inside a container use Python spellings and recursive representations (for \
example, `{'sample': [None, True]}`), and dictionary insertion order is the \
runtime order shown by `repr()`. Preserve empty containers as their Python \
representations; do not substitute JSON null or omit them.

Remove duplicate representation strings across all checkpoints and all \
invocations. Sort the remaining strings in ascending lexicographic order by \
Unicode code point, with no secondary key (for example, `"Z"` sorts before \
`"a"`). Return exactly `{"unique_values": [...]}`: `unique_values` is a JSON \
array of those Python-repr strings. No line numbers, invocation numbers, or \
counts are included."""


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_trace(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        fail(f"trace log does not exist: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    values = set()
    for line_number, raw_line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        match = EVENT_RE.match(raw_line)
        if not match:
            continue
        if not match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        try:
            locals_delta = ast.literal_eval(match.group("locals"))
        except (SyntaxError, ValueError) as exc:
            fail(f"cannot parse target locals on trace line {line_number}: {exc}")
        if not isinstance(locals_delta, dict):
            fail(f"target locals are not a dictionary on trace line {line_number}")

        value = locals_delta.get("generation_kwargs")
        if value is not None:
            if not isinstance(value, str):
                fail(f"generation_kwargs representation is not a string on trace line {line_number}")
            values.add(value)

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if not values:
        fail("target events contain no generation_kwargs observations")
    return sorted(values)


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    args = argument_parser.parse_args()

    answer = {"unique_values": parse_trace(args.trace_log)}
    payload = {
        "question_kind": "M3_ProgramState",
        "question": QUESTION,
        "template_answer": {"unique_values": ["str"]},
        "oracle_answer": answer,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
