#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scripts/translate.py"
TARGET_FUNC = "scripts.translate.translate_page"
TRACKED_FUNCS = {
    "scripts.translate.add_missing",
    "scripts.translate.generate_en_path",
    "scripts.translate.generate_lang_path",
    "scripts.translate.get_langs",
    "scripts.translate.get_prompt",
    "scripts.translate.translate_page",
    "scripts.translate.update_and_add",
    "scripts.translate.update_outdated",
}

QUESTION = """Run only the pytest test `fastapi_qa/translate_translate_page_m6_calls/files/testcase.py::TestIndirectTranslationBatch::test_generated_update_and_add_batch`. For the complete execution of that test, determine dynamic function coverage involving the target `scripts.translate.translate_page`, whose definition occupies lines 107-178 of `scripts/translate.py`.

The exact tracked function set is: `scripts.translate.add_missing`, `scripts.translate.generate_en_path`, `scripts.translate.generate_lang_path`, `scripts.translate.get_langs`, `scripts.translate.get_prompt`, `scripts.translate.translate_page`, `scripts.translate.update_and_add`, and `scripts.translate.update_outdated`. A tracked function is covered if at least one Python function `call` event for that exact function occurs anywhere during the selected test's execution. Count an event regardless of whether its caller is another tracked function, an untracked function, or whether it is reached directly or transitively; this is whole-test reachability, not merely direct calls from the target frame or calls made while the target is on the stack. Calls to functions outside the exact tracked set, including builtins, nested comprehension frames, and mock helper functions, are excluded.

Function identity is `frame.f_globals["__name__"] + "." + frame.f_code.co_qualname`; for example, an unrelated method could be `sample.mod.Widget.run`. Each initial frame entry, recursive entry, and Python `call` event produced when an existing generator or coroutine frame resumes is sufficient to mark its exact tracked function covered. Repeated calls and resumptions do not create repeated answer items: coverage is a set, so each covered function appears exactly once.

Return `oracle_answer` with exactly the shape `{"covered_functions": [{"file": <string>, "func": <string>}]}`. For each item, `file` is the repository-relative POSIX path formed by removing the `/testbed/` prefix from that call event's absolute frame filename, and `func` is the dotted identity defined above. Both fields are ordinary JSON strings; do not apply `repr()` or `str()` formatting to them. Remove duplicate `{file, func}` pairs, then sort items in ascending lexicographic order first by `file` and then by `func`, using Unicode code-point ordering (equivalent to Python sorting the two-string tuples). Because duplicates are removed, no further tie-breaker is needed. Emit no item for an uncovered tracked function. The resulting list is non-empty, so neither JSON `null` nor an empty-value convention applies."""

EVENT_RE = re.compile(
    r"(?P<file>/\S*scripts/translate\.py):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def repository_relative_file(raw_file: str) -> str:
    prefix = "/testbed/"
    if not raw_file.startswith(prefix):
        fail(f"target frame filename is not under {prefix}: {raw_file!r}")
    relative_file = raw_file[len(prefix) :]
    if relative_file != TARGET_FILE:
        fail(f"unexpected traced file: {relative_file}")
    return relative_file


def harvest(trace_path: Path) -> dict[str, list[dict[str, str]]]:
    if not trace_path.exists():
        fail(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        fail(f"trace log is empty: {trace_path}")

    target_events = 0
    target_calls = 0
    covered_pairs: set[tuple[str, str]] = set()

    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(raw_line)
        if match is None:
            continue
        function = match.group("func")
        event = match.group("event")
        if function == TARGET_FUNC:
            target_events += 1
            if event == "call":
                target_calls += 1
        if event == "call" and function in TRACKED_FUNCS:
            covered_pairs.add(
                (repository_relative_file(match.group("file")), function)
            )

    if target_events == 0:
        fail(f"trace contains zero events for {TARGET_FUNC}")
    if target_calls == 0:
        fail(f"trace contains zero call events for {TARGET_FUNC}")
    if len(covered_pairs) < 4:
        fail(f"expected at least 4 covered tracked functions, found {len(covered_pairs)}")
    covered_functions = [
        {"file": file_name, "func": function}
        for file_name, function in sorted(covered_pairs)
    ]
    return {"covered_functions": covered_functions}


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--trace-log", required=True, type=Path)
    argument_parser.add_argument("--out", required=True, type=Path)
    arguments = argument_parser.parse_args()

    payload = {
        "question_kind": "M6_InterProceduralCFG",
        "question": QUESTION,
        "template_answer": {
            "covered_functions": [{"file": "str", "func": "str"}]
        },
        "oracle_answer": harvest(arguments.trace_log),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    arguments.out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
