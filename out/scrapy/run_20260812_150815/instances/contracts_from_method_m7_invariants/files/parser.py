#!/usr/bin/env python3
import argparse
import ast
from collections import Counter
import json
import re
import sys
from pathlib import Path


TARGET_FILE = "scrapy/contracts/__init__.py"
TARGET_FUNC = "scrapy.contracts.ContractsManager.from_method"

URL_PREDICATE = (
    '("url" in kwargs) and '
    '(len(kwargs["url"]) % 5 == int(contract.args[0]) % 5)'
)
REQUEST_PREDICATE = (
    "(int(contract.args[0]) + len(request.url)) % 11 < len(contracts) % 11"
)
TOKEN_PREDICATE = (
    "int(contract.args[0]) % 504 != "
    "sum(int(item.args[0]) for item in contracts) % 504"
)
CLASS_PREDICATE = "request_cls is not Request"
SUM_PREDICATE = (
    "sum(int(item.args[0]) for item in contracts) % 17 != 1"
)

PREDICATE_LINES = {
    URL_PREDICATE: 176,
    REQUEST_PREDICATE: 186,
    TOKEN_PREDICATE: 164,
    CLASS_PREDICATE: 165,
    SUM_PREDICATE: 181,
}

QUESTION = """Run the pytest class selection `scrapy_qa/contracts_from_method_m7_invariants/files/testcase.py::TestContractsFromMethodInvariants`. It contains all twelve methods `test_01_single_dense` through `test_12_final_fault`; include every `test_...` method in that class, in ascending pytest-id (Unicode string) order, and aggregate observations across all of them. During that complete run, evaluate the five candidate predicates below in the target frame of `scrapy.contracts.ContractsManager.from_method` in `scrapy/contracts/__init__.py`.

Each predicate has its own observation point, shown after the colon. Evaluate it once for every target-frame Python `line` event at that absolute source line, immediately before that line executes, using the actual current local objects and normal Python expression semantics:

- `("url" in kwargs) and (len(kwargs["url"]) % 5 == int(contract.args[0]) % 5)`: line 176.
- `(int(contract.args[0]) + len(request.url)) % 11 < len(contracts) % 11`: line 186.
- `int(contract.args[0]) % 504 != sum(int(item.args[0]) for item in contracts) % 504`: line 164; `item` is only the predicate's generator-expression variable.
- `request_cls is not Request`: line 165, where `Request` is the `scrapy.http.Request` class imported in the target module.
- `sum(int(item.args[0]) for item in contracts) % 17 != 1`: line 181; `item` is only the predicate's generator-expression variable.

The source-line numbers are absolute, 1-based physical lines in the named repository file. A line event is attributed to the line where the executed statement or expression begins; it occurs before that line's operation, so assignments performed by earlier lines are already reflected while an assignment on the observed line is not. Blank, comment, decorator, `def`, and docstring lines contribute no observation unless Python actually emits a target-frame `line` event there. Count loop-body line events separately on every iteration. A target invocation is one `call` event for this function, numbered 1-based in chronological order across the ordered test methods; all invocations count, including ones that later return `None` or raise into the caller. Do not count `call`, `return`, or `exception` events as predicate observations.

For each predicate, `observations` is the total number of evaluations at its own observation point over the whole class run, and `violations` is the number whose result is false. `held_always` is exactly `violations == 0`, except that a predicate with zero observations is not evaluable and must be reported with `observations: 0`, `violations: 0`, and `held_always: false`.

Return exactly one JSON object with key `invariant_report`. Its value is a JSON array containing exactly one object per candidate predicate, with exactly these keys: `held_always` (JSON boolean), `observations` (JSON integer), `predicate` (JSON string copied verbatim from the candidate expression), and `violations` (JSON integer). Sort rows by `predicate` ascending in Unicode code-point order. Predicate strings are emitted directly as JSON strings and counts directly as JSON integers; no `repr()`, `str()`, deduplication, null, or empty-string sentinel is used. The predicate string is unique, so there is no further tie-break."""


TRACE_RE = re.compile(
    r"\s(?P<file>/\S+):(?P<line>\d+)\s+"
    + re.escape(TARGET_FUNC)
    + r"\s+event=(?P<event>call|line|return|exception)\b.*\slocals=(?P<locals>\{.*\})$"
)
CONTRACT_RE = re.compile(r"^_[A-Za-z]+\((?P<token>\d+)\)$")
CONTRACT_LIST_RE = re.compile(r"_[A-Za-z]+\((\d+)\)")
URL_RE = re.compile(r"'url': '([^']*)'")
REQUEST_RE = re.compile(r"^<[^ ]+ (?P<url>[^>]+)>$")


def _changed_locals(text):
    value = ast.literal_eval(text)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise RuntimeError(f"malformed traced locals mapping: {text}")
    return value


def _contract_token(state):
    raw = state.get("contract", "")
    match = CONTRACT_RE.fullmatch(raw)
    if match is None:
        raise RuntimeError(f"cannot decode contract local: {raw!r}")
    return int(match.group("token"))


def _contract_tokens(state):
    raw = state.get("contracts", "")
    tokens = [int(token) for token in CONTRACT_LIST_RE.findall(raw)]
    if not tokens:
        raise RuntimeError(f"cannot decode contracts local: {raw!r}")
    return tokens


def _kwargs_url(state):
    raw = state.get("kwargs", "")
    match = URL_RE.search(raw)
    return None if match is None else match.group(1)


def _request_url(state):
    raw = state.get("request", "")
    match = REQUEST_RE.fullmatch(raw)
    if match is None:
        raise RuntimeError(f"cannot decode request local: {raw!r}")
    return match.group("url")


def _evaluate(predicate, state):
    if predicate == URL_PREDICATE:
        url = _kwargs_url(state)
        return url is not None and len(url) % 5 == _contract_token(state) % 5
    if predicate == REQUEST_PREDICATE:
        tokens = _contract_tokens(state)
        return (
            _contract_token(state) + len(_request_url(state))
        ) % 11 < len(tokens) % 11
    if predicate == TOKEN_PREDICATE:
        tokens = _contract_tokens(state)
        return _contract_token(state) % 504 != sum(tokens) % 504
    if predicate == CLASS_PREDICATE:
        return state.get("request_cls") != "<class 'scrapy.http.request.Request'>"
    if predicate == SUM_PREDICATE:
        return sum(_contract_tokens(state)) % 17 != 1
    raise RuntimeError(f"unknown predicate: {predicate}")


def parse_trace(trace_path):
    if not trace_path.exists():
        raise RuntimeError(f"trace log is missing: {trace_path}")
    if trace_path.stat().st_size == 0:
        raise RuntimeError(f"trace log is empty: {trace_path}")

    events = []
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        match = TRACE_RE.search(raw_line)
        if match and match.group("file").replace("\\", "/").endswith(TARGET_FILE):
            events.append(
                (
                    match.group("event"),
                    int(match.group("line")),
                    _changed_locals(match.group("locals")),
                )
            )

    if not events:
        raise RuntimeError(
            f"trace contains zero events for {TARGET_FUNC} in {TARGET_FILE}"
        )
    if not any(event == "call" for event, _line, _locals in events):
        raise RuntimeError(f"trace contains no call event for {TARGET_FUNC}")
    if not any(event == "line" for event, _line, _locals in events):
        raise RuntimeError(f"trace contains no line event for {TARGET_FUNC}")

    observations = Counter()
    violations = Counter()
    state = None
    invocation_count = 0
    predicates_by_line = {
        line: predicate for predicate, line in PREDICATE_LINES.items()
    }

    for event, line, changed in events:
        if event == "call":
            if state is not None:
                raise RuntimeError("overlapping target invocations are unsupported")
            invocation_count += 1
            state = dict(changed)
            continue
        if state is None:
            raise RuntimeError(f"{event} event outside target invocation at line {line}")
        state.update(changed)

        if event == "line" and line in predicates_by_line:
            predicate = predicates_by_line[line]
            observations[predicate] += 1
            if not _evaluate(predicate, state):
                violations[predicate] += 1

        if event == "return":
            state = None

    if invocation_count == 0:
        raise RuntimeError(f"no invocations accounted for {TARGET_FUNC}")
    if state is not None:
        raise RuntimeError("target invocation did not finish")

    report = []
    for predicate in sorted(PREDICATE_LINES):
        observed = observations[predicate]
        violated = violations[predicate]
        report.append(
            {
                "held_always": observed > 0 and violated == 0,
                "observations": observed,
                "predicate": predicate,
                "violations": violated,
            }
        )
    return {"invariant_report": report}


def main():
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
        "oracle_answer": parse_trace(args.trace_log),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
