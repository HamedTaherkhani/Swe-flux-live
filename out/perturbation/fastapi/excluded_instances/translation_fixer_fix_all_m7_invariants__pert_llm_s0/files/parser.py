import argparse
import ast
import json
import re
from pathlib import Path


TARGET_FILE = "scripts/translation_fixer.py"
TARGET_FUNC = "scripts.translation_fixer.fix_all"
OBSERVATION_LINE = 110
EVENT_RE = re.compile(
    r"^(?:\S+ \S+ )?(?P<file>.+?):(?P<line>\d+) "
    r"(?P<func>\S+) event=(?P<event>\w+)"
)

QUESTION = """Run only the pytest test
`fastapi_qa/translation_fixer_fix_all_m7_invariants/files/testcase.py::TestTranslationFixAllInvariants::test_seeded_page_outcomes`
against the repository as provided. Consider the direct call of
`scripts.translation_fixer.fix_all` in `scripts/translation_fixer.py`.

For every execution of absolute, 1-based line 110 in that file, observe the
target function's local variables at the Python `line` event, immediately
before the statement beginning on line 110 executes. The line number is the
physical 1-based source line in the repository; for a multi-line statement a
`line` event belongs to the physical line where the executed
statement/expression begins. Decorator and `def` lines are not observations.
An "iteration" is the Nth such line-110 observation, in chronological order,
within an invocation. An invocation is one `call` of this exact function,
1-based in chronological order during the named test. Include observations
only from the exact `scripts.translation_fixer.fix_all` frame, not callees,
comprehension/generator frames, or functions with the same bare name.

At each observation, evaluate this candidate predicate verbatim using the
current Python local values:
`res == (sum((index + 1) * ord(char) for index, char in enumerate(page)) % 5 != 0)`.
Here `page` and `res` mean the values present in that target frame at the
observation point, and the expression has ordinary Python semantics.
"Always held" means the predicate evaluated to `True` at every observation
across all invocations. Count every observation separately; preserve
chronological order for evaluation, remove no duplicates, and apply no
sorting. A violating iteration is an observation where the predicate is
`False`. If there are zero observations, the result is not evaluable and the
run must be treated as invalid rather than emitting an answer.

Return exactly one JSON object with keys in this canonical order:
`is_invariant_always_held`, `total_iterations_observed`, and
`violating_iteration_count`. The first value is a JSON boolean; the other two
are base-10 JSON integers. Thus Python `True` is serialized as JSON `true`;
there are no strings, `repr()`-formatted values, exception names, function
names, line-number values, lists, nulls, absent values, or ordering
tie-breakers in the answer."""


def parse_changed_locals(line: str) -> dict[str, str]:
    try:
        locals_text = line.rsplit(" locals=", 1)[1]
    except IndexError as exc:
        raise ValueError(f"trace event has no locals payload: {line}") from exc
    try:
        payload = ast.literal_eval(locals_text)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"invalid locals payload: {locals_text}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"locals payload is not a dict: {locals_text}")
    return payload


def decode_local(state: dict[str, str], name: str):
    if name not in state:
        raise ValueError(f"required local {name!r} is absent at observation")
    try:
        return ast.literal_eval(state[name])
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"cannot decode local {name!r}: {state[name]!r}") from exc


def build_answer(trace_path: Path) -> dict[str, int | bool]:
    if not trace_path.is_file():
        raise FileNotFoundError(f"trace log is missing: {trace_path}")
    raw = trace_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"trace log is empty: {trace_path}")

    state: dict[str, str] = {}
    target_events = 0
    total = 0
    violations = 0

    for trace_line in raw.splitlines():
        match = EVENT_RE.match(trace_line)
        if match is None:
            continue
        file_name = match.group("file").replace("\\", "/")
        if not file_name.endswith(f"/{TARGET_FILE}"):
            continue
        if match.group("func") != TARGET_FUNC:
            continue

        target_events += 1
        event = match.group("event")
        if event == "call":
            state = {}
        state.update(parse_changed_locals(trace_line))

        if event != "line" or int(match.group("line")) != OBSERVATION_LINE:
            continue

        page = decode_local(state, "page")
        res = decode_local(state, "res")
        if not isinstance(page, str) or not isinstance(res, bool):
            raise TypeError(
                f"unexpected observation types: page={type(page).__name__}, "
                f"res={type(res).__name__}"
            )
        expected = (
            sum((index + 1) * ord(char) for index, char in enumerate(page)) % 5
            != 0
        )
        total += 1
        if res != expected:
            violations += 1

    if target_events == 0:
        raise ValueError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if total == 0:
        raise ValueError(
            f"trace contains zero line-{OBSERVATION_LINE} observations for "
            f"{TARGET_FUNC}"
        )

    return {
        "is_invariant_always_held": violations == 0,
        "total_iterations_observed": total,
        "violating_iteration_count": violations,
    }


def main() -> None:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--trace-log", type=Path, required=True)
    arg_parser.add_argument("--out", type=Path, required=True)
    args = arg_parser.parse_args()

    result = {
        "question_kind": "M7_Invariants",
        "question": QUESTION,
        "template_answer": {
            "is_invariant_always_held": "bool",
            "total_iterations_observed": "int",
            "violating_iteration_count": "int",
        },
        "oracle_answer": build_answer(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["oracle_answer"], sort_keys=True))


if __name__ == "__main__":
    main()
