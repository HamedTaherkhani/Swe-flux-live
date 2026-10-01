"""Reconstruct function activations from a harvested trace.log.

The harness tracer (payload/shared/files/trace_plugin.py) writes one record per
event and no frame id, so activations are rebuilt with a call stack: `call`
pushes, `return` pops, and `line`/`exception` events belong to the innermost
open activation of the same function. Only what checkpoints need is retained:
per-function invocation counts for the whole run, plus the full event list of
the first few invocations of each function.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

_EVENT_RE = re.compile(
    r"^(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ )?"
    r"(?P<file>\S+?):(?P<line>\d+) (?P<func>\S+) "
    r"event=(?P<event>call|line|return|exception)(?P<tail>.*)$",
    re.DOTALL,
)
_MARKER_RE = re.compile(r"^(?:\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ )?\[TRACE\]")
_LOCALS_MARK = " locals="


@dataclass
class Activation:
    """One call..return segment of a traced function."""

    func: str
    file: str
    call_line: int
    call_tail: str = ""
    lines: List[int] = field(default_factory=list)
    exceptions: List[Tuple[int, str]] = field(default_factory=list)
    return_line: Optional[int] = None
    return_tail: Optional[str] = None
    last_event: str = "call"
    last_event_line: int = 0
    keep: bool = False
    seq: int = 0

    @property
    def closed(self) -> bool:
        return self.return_line is not None


@dataclass
class FunctionTrace:
    func: str
    file: str
    # call line -> number of activations that started there. A fresh invocation
    # starts at the function's first line; a generator resume starts at a yield.
    # Before Python 3.11 the tracer has no qualname, so same-named functions of
    # one module share `func` and are told apart only by their call line.
    calls_by_line: Dict[int, int] = field(default_factory=dict)
    kept: Dict[int, List[Activation]] = field(default_factory=dict)


@dataclass
class TraceModel:
    functions: Dict[Tuple[str, str], FunctionTrace] = field(default_factory=dict)
    events: int = 0
    orphan_events: int = 0
    unclosed: int = 0


def iter_records(path: Path) -> Iterator[Tuple[str, int, str, str, str]]:
    """Yield (file, line, func, event, tail). A repr may contain raw newlines,
    so physical lines that do not start a record continue the previous one."""
    pending: Optional[List[str]] = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            text = raw.rstrip("\n")
            if _EVENT_RE.match(text):
                if pending is not None:
                    yield _split("\n".join(pending))
                pending = [text]
            elif _MARKER_RE.match(text):
                # [TRACE][START] banners are records of their own, not repr text.
                if pending is not None:
                    yield _split("\n".join(pending))
                pending = None
            elif pending is not None:
                pending.append(text)
    if pending is not None:
        yield _split("\n".join(pending))


def _split(record: str) -> Tuple[str, int, str, str, str]:
    match = _EVENT_RE.match(record)
    assert match is not None
    return (
        match.group("file").replace("\\", "/"),
        int(match.group("line")),
        match.group("func"),
        match.group("event"),
        match.group("tail"),
    )


def parse_trace(
    path: Path,
    *,
    is_primary: Callable[[str], bool],
    keep_invocations: int = 1,
) -> TraceModel:
    """Build the activation model. Events are retained only for the first
    `keep_invocations` activations per (file, function, call line)."""
    model = TraceModel()
    stack: List[Activation] = []

    for file, line, func, event, tail in iter_records(path):
        model.events += 1
        if event == "call":
            activation = Activation(
                func=func, file=file, call_line=line, last_event_line=line, seq=model.events
            )
            if is_primary(func):
                ftrace = model.functions.get((file, func))
                if ftrace is None:
                    ftrace = FunctionTrace(func=func, file=file)
                    model.functions[(file, func)] = ftrace
                ftrace.calls_by_line[line] = ftrace.calls_by_line.get(line, 0) + 1
                bucket = ftrace.kept.setdefault(line, [])
                if len(bucket) < keep_invocations:
                    activation.keep = True
                    activation.call_tail = tail
                    bucket.append(activation)
            stack.append(activation)
            continue

        # Re-synchronise when the innermost frame is not the one reporting,
        # e.g. tracing was enabled while that frame was already running.
        index = len(stack) - 1
        while index >= 0 and stack[index].func != func:
            index -= 1
        if index < 0:
            model.orphan_events += 1
            continue
        if index != len(stack) - 1:
            model.unclosed += len(stack) - 1 - index
            del stack[index + 1:]
        activation = stack[-1]

        if event == "line":
            if activation.keep:
                activation.lines.append(line)
        elif event == "exception":
            if activation.keep:
                activation.exceptions.append((line, tail))
        else:
            activation.return_line = line
            if activation.keep:
                activation.return_tail = tail
            stack.pop()
            continue
        activation.last_event = event
        activation.last_event_line = line

    model.unclosed += len(stack)
    return model


def split_tail(tail: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """Split an event tail into (prefix, locals). The locals dict is the repr of
    a str->str mapping; a repr inside the prefix may itself contain the marker,
    so take the first position whose remainder parses."""
    start = 0
    while True:
        pos = tail.find(_LOCALS_MARK, start)
        if pos < 0:
            return tail, None
        try:
            value = ast.literal_eval(tail[pos + len(_LOCALS_MARK):].strip())
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            value = None
        if isinstance(value, dict):
            return tail[:pos], {str(k): str(v) for k, v in value.items()}
        start = pos + 1


def tail_field(prefix: str, name: str) -> Optional[str]:
    marker = f" {name}="
    pos = prefix.find(marker)
    if pos < 0:
        return None
    return prefix[pos + len(marker):]
