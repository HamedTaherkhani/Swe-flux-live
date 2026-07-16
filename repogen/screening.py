"""Post-generation screening: category-aware runtime exclusion rules.

Runs AFTER generation over a run directory. Each rule inspects one instance's
artifacts (oracle.json, trace.log, pytest.log) and decides pass/fail with a
reason. Instances failing any rule are moved to <run_dir>/excluded_instances/
(never deleted) and the verdicts land in screening_report.json.

Rules (Strategy objects, same pattern as agent backends):
- oracle_valid      oracle.json exists, is valid JSON, has the 4 required keys,
                    question_kind matches, oracle_answer is not empty.
- template_valid    template_answer is a well-formed type skeleton and
                    oracle_answer structurally conforms to it.
- test_passed       the harvested pytest run actually passed.
- answer_rich       the oracle answer has enough substance for its category.
- trace_rich        the traced execution shows enough runtime behavior for its
                    category (line events, distinct lines, calls, repetitions,
                    exception events).
"""

from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------
# Trace statistics
# --------------------------------------------------------------------------

_TRACE_EVENT_RE = re.compile(
    r" (?P<path>/\S+?):(?P<lineno>\d+) (?P<func>\S+) event=(?P<event>call|line|return|exception)\b"
)


@dataclass
class TraceStats:
    total_events: int = 0
    line_events: int = 0
    call_events: int = 0
    return_events: int = 0
    exception_events: int = 0
    distinct_lines: int = 0
    distinct_functions: int = 0
    max_line_repetition: int = 0

    @classmethod
    def from_log(cls, trace_text: str) -> "TraceStats":
        stats = cls()
        line_counts: dict[tuple[str, int], int] = {}
        functions: set[str] = set()
        for match in _TRACE_EVENT_RE.finditer(trace_text):
            event = match.group("event")
            stats.total_events += 1
            functions.add(match.group("func"))
            if event == "line":
                stats.line_events += 1
                key = (match.group("path"), int(match.group("lineno")))
                line_counts[key] = line_counts.get(key, 0) + 1
            elif event == "call":
                stats.call_events += 1
            elif event == "return":
                stats.return_events += 1
            elif event == "exception":
                stats.exception_events += 1
        stats.distinct_lines = len(line_counts)
        stats.distinct_functions = len(functions)
        stats.max_line_repetition = max(line_counts.values(), default=0)
        return stats


# --------------------------------------------------------------------------
# Category thresholds
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """Minimum runtime substance an instance must show. Defaults are the
    baseline; CATEGORY_THRESHOLDS overrides per category."""

    min_line_events: int = 20
    min_distinct_lines: int = 8
    min_call_events: int = 1
    min_distinct_functions: int = 1
    min_exception_events: int = 0
    min_line_repetition: int = 1
    min_answer_leaves: int = 4


CATEGORY_THRESHOLDS: dict[str, Thresholds] = {
    "S1_IntraProceduralCFG": Thresholds(min_distinct_lines=10, min_answer_leaves=8),
    "S2_Loops": Thresholds(min_line_events=30, min_line_repetition=3),
    "S3_ProgramState": Thresholds(min_answer_leaves=6),
    "S4_DataFlow": Thresholds(min_answer_leaves=12),
    "S5_Exceptions": Thresholds(min_exception_events=1),
    "S6_InterProceduralCFG": Thresholds(min_call_events=3, min_distinct_functions=2),
    "M1_IntraProceduralCFG": Thresholds(
        min_distinct_lines=12, min_call_events=3, min_answer_leaves=10
    ),
    "M2_Loops": Thresholds(min_line_events=50, min_line_repetition=5),
    "M3_ProgramState": Thresholds(min_answer_leaves=12),
    "M4_DataFlow": Thresholds(min_answer_leaves=15),
    "M5_Exceptions": Thresholds(min_exception_events=2),
    "M6_InterProceduralCFG": Thresholds(
        min_call_events=5, min_distinct_functions=3, min_answer_leaves=6
    ),
    "M7_Invariants": Thresholds(min_line_repetition=3, min_answer_leaves=6),
}


def thresholds_for(category: str) -> Thresholds:
    return CATEGORY_THRESHOLDS.get(category, Thresholds())


# --------------------------------------------------------------------------
# Instance context
# --------------------------------------------------------------------------

REQUIRED_ORACLE_KEYS = {"question_kind", "question", "template_answer", "oracle_answer"}
NON_INSTANCE_DIRS = {"shared", "qa_artifacts"}

_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": (int, float),
    "number": (int, float),
    "bool": bool,
    "null": type(None),
    "none": type(None),
    "any": object,
}


@dataclass
class InstanceContext:
    instance_id: str
    category: str
    instance_dir: Path
    trace_log: Optional[Path]
    pytest_log: Optional[Path]
    oracle: Optional[dict] = None
    oracle_error: str = ""
    _trace_stats: Optional[TraceStats] = field(default=None, repr=False)

    @classmethod
    def load(cls, instance_dir: Path, category: str, log_dirs: list[Path]) -> "InstanceContext":
        ctx = cls(
            instance_id=instance_dir.name,
            category=category,
            instance_dir=instance_dir,
            trace_log=_find_artifact("trace.log", instance_dir, log_dirs),
            pytest_log=_find_artifact("pytest.log", instance_dir, log_dirs),
        )
        oracle_path = instance_dir / "oracle.json"
        if not oracle_path.is_file():
            ctx.oracle_error = "oracle.json missing"
        else:
            try:
                ctx.oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                ctx.oracle_error = f"oracle.json invalid JSON: {e}"
        return ctx

    @property
    def trace_stats(self) -> Optional[TraceStats]:
        if self._trace_stats is None and self.trace_log and self.trace_log.is_file():
            self._trace_stats = TraceStats.from_log(
                self.trace_log.read_text(encoding="utf-8", errors="replace")
            )
        return self._trace_stats

    @property
    def thresholds(self) -> Thresholds:
        return thresholds_for(self.category)


def _find_artifact(name: str, instance_dir: Path, log_dirs: list[Path]) -> Optional[Path]:
    candidates = [instance_dir / name]
    for log_dir in log_dirs:
        candidates.append(log_dir / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


@dataclass
class RuleResult:
    rule: str
    passed: bool
    reason: str = ""


class ScreeningRule(ABC):
    name = "abstract"

    @abstractmethod
    def check(self, ctx: InstanceContext) -> RuleResult:
        ...

    def _fail(self, reason: str) -> RuleResult:
        return RuleResult(self.name, False, reason)

    def _pass(self, reason: str = "") -> RuleResult:
        return RuleResult(self.name, True, reason)


class OracleValidRule(ScreeningRule):
    name = "oracle_valid"

    def check(self, ctx: InstanceContext) -> RuleResult:
        if ctx.oracle is None:
            return self._fail(ctx.oracle_error or "oracle.json unreadable")
        if not isinstance(ctx.oracle, dict):
            return self._fail("oracle.json is not a JSON object")
        missing = REQUIRED_ORACLE_KEYS - set(ctx.oracle)
        if missing:
            return self._fail(f"missing keys: {sorted(missing)}")
        if ctx.oracle.get("question_kind") != ctx.category:
            return self._fail(
                f"question_kind {ctx.oracle.get('question_kind')!r} != planned {ctx.category!r}"
            )
        if not str(ctx.oracle.get("question", "")).strip():
            return self._fail("question text is empty")
        answer = ctx.oracle.get("oracle_answer")
        if _is_effectively_empty(answer):
            return self._fail("oracle_answer is empty")
        return self._pass()


class TemplateValidRule(ScreeningRule):
    name = "template_valid"

    def check(self, ctx: InstanceContext) -> RuleResult:
        if ctx.oracle is None:
            return self._fail("no oracle to validate")
        template = ctx.oracle.get("template_answer")
        answer = ctx.oracle.get("oracle_answer")
        errors: list[str] = []
        _match_template(template, answer, "$", errors)
        if errors:
            return self._fail("; ".join(errors[:5]))
        return self._pass()


class TestPassedRule(ScreeningRule):
    name = "test_passed"

    _SUMMARY_RE = re.compile(r"=+ (.*?) =+\s*$", re.MULTILINE)

    def check(self, ctx: InstanceContext) -> RuleResult:
        if ctx.pytest_log is None:
            return self._fail("pytest.log not found")
        text = ctx.pytest_log.read_text(encoding="utf-8", errors="replace")
        summaries = self._SUMMARY_RE.findall(text)
        summary = summaries[-1] if summaries else ""
        if re.search(r"\b\d+ (failed|error)", summary) or "FAILURES" in text:
            return self._fail(f"pytest reported failures: {summary.strip()!r}")
        if not re.search(r"\b\d+ passed", summary):
            return self._fail(f"no passing tests in summary: {summary.strip()!r}")
        return self._pass(summary.strip())


class AnswerRichRule(ScreeningRule):
    name = "answer_rich"

    def check(self, ctx: InstanceContext) -> RuleResult:
        if ctx.oracle is None:
            return self._fail("no oracle to inspect")
        leaves = _count_leaves(ctx.oracle.get("oracle_answer"))
        minimum = ctx.thresholds.min_answer_leaves
        if leaves < minimum:
            return self._fail(
                f"answer too small: {leaves} leaf values < required {minimum} "
                f"for {ctx.category}"
            )
        return self._pass(f"{leaves} leaf values")


class TraceRichRule(ScreeningRule):
    name = "trace_rich"

    def check(self, ctx: InstanceContext) -> RuleResult:
        stats = ctx.trace_stats
        if stats is None:
            return self._fail("trace.log not found")
        if stats.total_events == 0:
            return self._fail("trace.log has zero trace events")
        t = ctx.thresholds
        problems = []
        if stats.line_events < t.min_line_events:
            problems.append(f"line events {stats.line_events} < {t.min_line_events}")
        if stats.distinct_lines < t.min_distinct_lines:
            problems.append(
                f"distinct lines {stats.distinct_lines} < {t.min_distinct_lines}"
            )
        if stats.call_events < t.min_call_events:
            problems.append(f"call events {stats.call_events} < {t.min_call_events}")
        if stats.distinct_functions < t.min_distinct_functions:
            problems.append(
                f"distinct functions {stats.distinct_functions} < {t.min_distinct_functions}"
            )
        if stats.exception_events < t.min_exception_events:
            problems.append(
                f"exception events {stats.exception_events} < {t.min_exception_events}"
            )
        if stats.max_line_repetition < t.min_line_repetition:
            problems.append(
                f"max line repetition {stats.max_line_repetition} < {t.min_line_repetition}"
            )
        if problems:
            return self._fail(
                f"execution too shallow for {ctx.category}: " + "; ".join(problems)
            )
        return self._pass(
            f"lines={stats.line_events} distinct={stats.distinct_lines} "
            f"calls={stats.call_events} funcs={stats.distinct_functions} "
            f"exc={stats.exception_events} rep={stats.max_line_repetition}"
        )


DEFAULT_RULES: list[ScreeningRule] = [
    OracleValidRule(),
    TemplateValidRule(),
    TestPassedRule(),
    AnswerRichRule(),
    TraceRichRule(),
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _is_effectively_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return all(_is_effectively_empty(v) for v in value.values()) if value else True
    if isinstance(value, list):
        return all(_is_effectively_empty(v) for v in value) if value else True
    if isinstance(value, str):
        return not value.strip()
    return False  # numbers/bools count as content


def _count_leaves(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_leaves(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_leaves(v) for v in value)
    return 1


def _match_template(template: Any, answer: Any, path: str, errors: list[str]) -> None:
    if isinstance(template, dict):
        if not isinstance(answer, dict):
            errors.append(f"{path}: expected object, got {type(answer).__name__}")
            return
        if set(template) != set(answer):
            errors.append(
                f"{path}: keys differ (template {sorted(template)}, answer {sorted(answer)})"
            )
            return
        for key in template:
            _match_template(template[key], answer[key], f"{path}.{key}", errors)
    elif isinstance(template, list):
        if not template:
            errors.append(f"{path}: template list has no element schema")
            return
        if not isinstance(answer, list):
            errors.append(f"{path}: expected list, got {type(answer).__name__}")
            return
        for index, item in enumerate(answer):
            _match_template(template[0], item, f"{path}[{index}]", errors)
    elif isinstance(template, str):
        expected = _TYPE_MAP.get(template.strip().lower())
        if expected is None:
            errors.append(f"{path}: template leaf {template!r} is not a type name")
        elif expected in (int, (int, float)) and isinstance(answer, bool):
            # bool is a subclass of int; reject it for numeric leaves
            errors.append(f"{path}: expected {template}, got bool")
        elif expected is not object and not isinstance(answer, expected):
            errors.append(f"{path}: expected {template}, got {type(answer).__name__}")
    else:
        errors.append(
            f"{path}: template leaf must be a type-name string, got {type(template).__name__}"
        )


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


@dataclass
class InstanceVerdict:
    instance_id: str
    category: str
    kept: bool
    results: list[RuleResult]

    def failed_rules(self) -> list[str]:
        return [r.rule for r in self.results if not r.passed]

    def as_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "category": self.category,
            "kept": self.kept,
            "results": [asdict(r) for r in self.results],
        }


class Screener:
    def __init__(self, run_dir: Path, rules: Optional[list[ScreeningRule]] = None):
        self.run_dir = Path(run_dir)
        self.instances_root = self.run_dir / "instances"
        self.excluded_root = self.run_dir / "excluded_instances"
        self.rules = rules if rules is not None else DEFAULT_RULES

    def screen(self, dry_run: bool = False) -> list[InstanceVerdict]:
        categories = self._categories_from_plan()
        verdicts: list[InstanceVerdict] = []
        for instance_dir in sorted(self.instances_root.iterdir()):
            if not instance_dir.is_dir() or instance_dir.name in NON_INSTANCE_DIRS:
                continue
            instance_id = instance_dir.name
            category = categories.get(instance_id) or self._category_from_oracle(
                instance_dir
            )
            ctx = InstanceContext.load(
                instance_dir,
                category,
                log_dirs=[
                    self.instances_root / "qa_artifacts" / instance_id,
                    self.run_dir / "logs" / instance_id / "harvest",
                ],
            )
            results = []
            for rule in self.rules:
                result = rule.check(ctx)
                results.append(result)
            verdict = InstanceVerdict(
                instance_id=instance_id,
                category=category,
                kept=all(r.passed for r in results),
                results=results,
            )
            verdicts.append(verdict)
            if not verdict.kept and not dry_run:
                self._exclude(instance_dir)
        self._write_report(verdicts, dry_run)
        return verdicts

    def _exclude(self, instance_dir: Path) -> None:
        self.excluded_root.mkdir(parents=True, exist_ok=True)
        destination = self.excluded_root / instance_dir.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(instance_dir), str(destination))

    def _categories_from_plan(self) -> dict[str, str]:
        plan_path = self.run_dir / "plan.json"
        if not plan_path.is_file():
            return {}
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            return {p["instance_id"]: p["category"] for p in plan}
        except (json.JSONDecodeError, KeyError, TypeError):
            return {}

    @staticmethod
    def _category_from_oracle(instance_dir: Path) -> str:
        oracle_path = instance_dir / "oracle.json"
        try:
            data = json.loads(oracle_path.read_text(encoding="utf-8"))
            return str(data.get("question_kind", ""))
        except (OSError, json.JSONDecodeError):
            return ""

    def _write_report(self, verdicts: list[InstanceVerdict], dry_run: bool) -> None:
        kept = [v for v in verdicts if v.kept]
        report = {
            "run_dir": str(self.run_dir),
            "dry_run": dry_run,
            "total": len(verdicts),
            "kept": len(kept),
            "excluded": len(verdicts) - len(kept),
            "verdicts": [v.as_dict() for v in verdicts],
        }
        report_path = self.run_dir / "screening_report.json"
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
