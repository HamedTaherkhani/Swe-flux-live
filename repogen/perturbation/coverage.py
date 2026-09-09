"""Coverage signatures from harvest traces.

`trace_plugin.py` already writes a line-level execution trace during harvest.
Parsing it into a set of executed (file, line) locations plus consecutive-line
edges gives a cheap fitness signal: did this perturbation reach code the
original did not? The ordered event sequence is kept separately so exact
execution-path equality can be distinguished from mere coverage equality.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet, Optional, Tuple

# Matches trace_plugin output, e.g.
#   2026-08-12 23:00:46.379 /testbed/src/click/utils.py:241 click.utils.echo event=line ...
_TRACE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\s+"
    r"(?P<path>[^:]+):(?P<line>\d+)\s+(?P<func>\S+)\s+event=(?P<event>\w+)"
)

Location = Tuple[str, int]
Edge = Tuple[str, int, int]
TraceEvent = Tuple[str, int, str, str]


def _normalize_path(path: str) -> str:
    """Drop the container prefix so signatures compare across runs."""
    p = path.replace("\\", "/")
    marker = "/testbed/"
    idx = p.find(marker)
    return p[idx + len(marker):] if idx != -1 else p


@dataclass(frozen=True)
class CoverageSignature:
    lines: FrozenSet[Location] = field(default_factory=frozenset)
    edges: FrozenSet[Edge] = field(default_factory=frozenset)
    events: Tuple[TraceEvent, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.events or self.lines)

    def new_lines_vs(self, baseline: "CoverageSignature") -> FrozenSet[Location]:
        return frozenset(self.lines - baseline.lines)

    def new_edges_vs(self, baseline: "CoverageSignature") -> FrozenSet[Edge]:
        return frozenset(self.edges - baseline.edges)

    def same_path_as(self, baseline: "CoverageSignature") -> bool:
        """Exact ordered event equality (stricter than coverage equality)."""
        return bool(self.events) and self.events == baseline.events

    @property
    def key(self) -> int:
        return hash(self.lines)


class CoverageExtractor:
    def extract_text(self, text: str) -> CoverageSignature:
        lines: set[Location] = set()
        edges: set[Edge] = set()
        events: list[TraceEvent] = []
        last_by_func: dict[str, int] = {}

        for raw in text.splitlines():
            m = _TRACE_RE.match(raw)
            if not m:
                continue
            event = m.group("event")
            if event not in ("line", "call", "return", "exception"):
                continue
            path = _normalize_path(m.group("path"))
            lineno = int(m.group("line"))
            func = m.group("func")
            lines.add((path, lineno))
            events.append((path, lineno, func, event))
            prev = last_by_func.get(func)
            if prev is not None and prev != lineno:
                edges.add((func, prev, lineno))
            last_by_func[func] = lineno

        return CoverageSignature(frozenset(lines), frozenset(edges), tuple(events))

    def extract_file(self, path: Path) -> Optional[CoverageSignature]:
        try:
            return self.extract_text(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None
