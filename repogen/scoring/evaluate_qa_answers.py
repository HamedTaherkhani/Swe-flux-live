#!/usr/bin/env python3
"""Evaluate QA answers against oracle answers.

Usage:
  python3 evaluation_scripts/evaluate_qa_answers.py --tool cursor --model gpt-5.3-codex-high --repo Sympy
  python3 evaluation_scripts/evaluate_qa_answers.py --tool cursor --model gpt-5.3-codex-high --repo all
  python3 evaluation_scripts/evaluate_qa_answers.py --tool cursor --model gpt-5.3-codex-high
  python3 evaluation_scripts/evaluate_qa_answers.py --tool llm --vendor openai --model gpt-5.4-2026-03-05 --repo Sympy
  python3 evaluation_scripts/evaluate_qa_answers.py --tool llm --vendor openai --model gpt-5.4-2026-03-05
  python3 evaluation_scripts/evaluate_qa_answers.py --tool llm --vendor vllm --model local-vllm --repo Sympy
  python3 evaluation_scripts/evaluate_qa_answers.py --all
"""

from __future__ import annotations

import ast
import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
EXCEL_EXCLUDED_TOOLS = {"claude_code", "mini-swe-agent", "mini_swe_agent"}

# Copied from RepoBehave's evaluation_scripts/evaluate_qa_answers.py.
# Only change: count_question_kinds (used solely by the Excel report) is
# stubbed when unavailable, so the comparison core imports standalone.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
try:
    from count_question_kinds import count_question_kinds  # noqa: E402
except ImportError:
    def count_question_kinds(_repo_dir):  # type: ignore[misc]
        return Counter()


@dataclass
class CompareResult:
    ok: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class EvalTarget:
    tool: str
    model: str
    repo: str
    vendor: Optional[str] = None

    def label(self) -> str:
        if self.tool.lower() == "llm" and self.vendor:
            return f"{self.tool}/{self.vendor}/{self.model}/{self.repo}"
        return f"{self.tool}/{self.model}/{self.repo}"


@dataclass
class EvalStats:
    total: int = 0
    correct: int = 0
    invalid_pred: int = 0
    missing_pred: int = 0
    missing_oracle: int = 0
    per_kind_total: Dict[str, int] = field(default_factory=dict)
    per_kind_correct: Dict[str, int] = field(default_factory=dict)
    failed_instances: List[Tuple[str, str, str]] = field(default_factory=list)  # (repo, instance, reason)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def pick_answer_payload(answer_data: Any) -> Any:
    if isinstance(answer_data, dict):
        if "oracle_answer" in answer_data:
            return answer_data["oracle_answer"]
        if "answer" in answer_data:
            return answer_data["answer"]
    return answer_data


def normalize_path(s: str) -> str:
    out = s.strip().replace("\\", "/")
    while "//" in out:
        out = out.replace("//", "/")
    if out.startswith("./"):
        out = out[2:]
    if out.endswith("/") and len(out) > 1:
        out = out[:-1]
    return out


def dotted_to_path(s: str) -> str:
    if "/" in s or "\\" in s:
        return normalize_path(s)
    if "." in s:
        return normalize_path(s.replace(".", "/"))
    return s


def normalize_identifier(s: str, key_name: str) -> List[str]:
    vals = set()
    raw = s.strip()
    vals.add(raw)
    vals.add(normalize_path(raw))
    vals.add(dotted_to_path(raw))

    if "file" in key_name.lower():
        for v in list(vals):
            if v.endswith(".py"):
                vals.add(v[:-3])
            else:
                vals.add(v + ".py")

    return list(vals)


ALT_SEPARATOR = "|||"


def _is_alt_string(s: str) -> bool:
    if ALT_SEPARATOR not in s:
        return False
    parts = [p.strip() for p in s.split(ALT_SEPARATOR)]
    return len(parts) >= 2 and all(part != "" for part in parts)


def _enum_canonical(s: str) -> str:
    token = s.strip()
    if token.startswith("<") and token.endswith(">") and len(token) > 2:
        token = token[1:-1].strip()
    if "." in token:
        token = token.split(".")[-1]
    return token.upper()


# Keys whose string values are code identifiers (paths / functions / classes).
# For these we additionally absorb format-only differences: a repo-relative path
# prefix (`keras/src/...` vs `src/...`), a class repr wrapper
# (`<class 'a.b.C'>` vs `C`), or a bare-vs-qualified name (`_select_factory` vs
# `faker.proxy._select_factory`). These never change *which* entity is named --
# a different module/class/function still fails -- so they only forgive the
# naming convention, not a wrong answer.
_IDENTIFIER_KEYS = {
    "file", "func", "cls", "class", "concrete_class",
    "dispatched_file", "dispatched_function", "dispatched_class",
}
_CLASS_REPR_RE = re.compile(r"^<class\s+'([^']+)'>$")
_COND_PREFIX_RE = re.compile(r"^(if|elif|while|for|assert)\b\s*")


def _strip_class_repr(s: str) -> str:
    m = _CLASS_REPR_RE.match(s.strip())
    return m.group(1) if m else s.strip()


def _strip_condition(s: str) -> str:
    t = _COND_PREFIX_RE.sub("", s.strip())
    if t.endswith(":"):
        t = t[:-1]
    return t.strip()


def _component_suffix_match(a: str, b: str) -> bool:
    """True if one dotted/slash identifier is a tail-component suffix of the
    other (e.g. `_select_factory` of `faker.proxy._select_factory`, or
    `src/m/metric.py` of `keras/src/m/metric.py`). Requires component-boundary
    alignment, so `a.foo` and `b.foo` (divergent modules) do NOT match."""
    sa = [x for x in re.split(r"[./]", a.strip()) if x]
    sb = [x for x in re.split(r"[./]", b.strip()) if x]
    if not sa or not sb:
        return False
    short, long = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return long[-len(short):] == short


def _compare_string_single(expected: str, pred: str, key_name: str) -> bool:
    if expected == pred:
        return True

    kl = key_name.lower()
    # Condition rendering: `if not (x):` vs the bare expression `not (x)`.
    if kl == "condition" and _strip_condition(expected) == _strip_condition(pred):
        return True
    # Identifier keys: forgive class-repr wrappers and path-prefix / qualifier.
    if kl in _IDENTIFIER_KEYS:
        e_id, p_id = _strip_class_repr(expected), _strip_class_repr(pred)
        if e_id == p_id or _component_suffix_match(e_id, p_id):
            return True

    e_norm = normalize_identifier(expected, key_name)
    p_norm = normalize_identifier(pred, key_name)
    if any(a == b for a in e_norm for b in p_norm):
        return True

    if key_name.lower() in {"type", "status"}:
        return _enum_canonical(expected) == _enum_canonical(pred)

    return False


def compare_strings(expected: str, pred: str, key_name: str) -> bool:
    if _compare_string_single(expected, pred, key_name):
        return True
    if _is_alt_string(expected):
        return any(_compare_string_single(alt.strip(), pred, key_name) for alt in expected.split(ALT_SEPARATOR))
    return False


# Answer fields that are semantically *sets* (the question canonicalizes them as
# "sorted"/"unique"/"set", so element order carries no meaning). These are
# compared as multisets so a correct set of elements is not failed merely for
# being ordered differently than the oracle. Sequence/history/path/geometry
# fields (executed_path, function_call_order, dispatch_sequence, *_history,
# output_rectangles, ...) are deliberately NOT listed: their order is the answer.
ORDER_INSENSITIVE_LIST_KEYS = {
    "observed_def_use_pairs",
    "covered_def_use_pairs",
    "covered_du_pairs",
    "uncovered_du_pairs_list",
    "covered_lines",
    "covered_functions",
    "union_lines_sorted",
    "intersection_lines_sorted",
    "lines_covered_by_only_one_test",
    "exception_types",
    "unique_values",
    "subtype_value_set",
    "guess_value_set",
    "safe_tests",
    "crashing_tests",
}


def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


_MAPPINGPROXY_RE = re.compile(r"^mappingproxy\((.*)\)$", re.DOTALL)


def normalize_special_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    match = _MAPPINGPROXY_RE.fullmatch(text)
    if not match:
        return value

    inner = match.group(1).strip()
    try:
        parsed = ast.literal_eval(inner)
    except Exception:
        return value
    return parsed if isinstance(parsed, dict) else value


def _try_parse_container(s: str) -> Tuple[Any, bool]:
    """Parse a list/dict that the model serialized to a string.

    Returns (value, True) only if it parses to a real list/dict; the caller then
    compares the parsed structure element-by-element, so wrong *content* still
    fails -- this forgives only `[1,2]` vs "[1,2]", not a wrong list.
    """
    t = s.strip()
    if not t or t[0] not in "[{":
        return None, False
    for parser in (json.loads, ast.literal_eval):
        try:
            v = parser(t)
            if isinstance(v, (list, dict)):
                return v, True
        except Exception:
            pass
    return None, False


def _coerce_scalar_string(s: str) -> Tuple[Any, bool]:
    """Coerce a scalar the model emitted as a string ('282', 'true', 'null')."""
    t = s.strip()
    low = t.lower()
    if low == "true":
        return True, True
    if low == "false":
        return False, True
    if low in ("null", "none"):
        return None, True
    if re.fullmatch(r"[+-]?\d+", t):
        try:
            return int(t), True
        except Exception:
            return None, False
    try:
        return float(t), True
    except Exception:
        return None, False


def _compare_list_unordered(
    expected: List[Any],
    pred: List[Any],
    *,
    key_name: str,
    path: str,
    float_tol: float,
) -> CompareResult:
    """Multiset comparison: every expected element must match a distinct pred
    element (using the same element-wise rules as compare_values), regardless of
    order. Lengths are already known to be equal at the call site."""
    used = [False] * len(pred)
    for i, e_item in enumerate(expected):
        matched = False
        for j, p_item in enumerate(pred):
            if used[j]:
                continue
            if compare_values(
                e_item, p_item, key_name=key_name, path=f"{path}[{i}]", float_tol=float_tol
            ).ok:
                used[j] = True
                matched = True
                break
        if not matched:
            return CompareResult(
                False, f"{path}: unmatched_element (order-insensitive) {json.dumps(e_item)[:80]}"
            )
    return CompareResult(True)


def compare_values(
    expected: Any,
    pred: Any,
    *,
    key_name: str,
    path: str,
    float_tol: float,
) -> CompareResult:
    expected = normalize_special_value(expected)
    pred = normalize_special_value(pred)

    if is_number(expected) and is_number(pred):
        if math.isclose(float(expected), float(pred), rel_tol=float_tol, abs_tol=float_tol):
            return CompareResult(True)
        return CompareResult(False, f"{path}: number_mismatch {expected} != {pred}")

    if isinstance(expected, str) and isinstance(pred, str):
        if compare_strings(expected, pred, key_name):
            return CompareResult(True)
        return CompareResult(False, f"{path}: string_mismatch {expected} != {pred}")

    if isinstance(expected, list):
        if isinstance(pred, str):
            parsed, ok = _try_parse_container(pred)
            if ok and isinstance(parsed, list):
                pred = parsed
        if not isinstance(pred, list):
            return CompareResult(False, f"{path}: type_mismatch expected=list got={type(pred).__name__}")
        if len(expected) != len(pred):
            return CompareResult(False, f"{path}: list_len {len(expected)} != {len(pred)}")
        if key_name in ORDER_INSENSITIVE_LIST_KEYS:
            return _compare_list_unordered(
                expected, pred, key_name=key_name, path=path, float_tol=float_tol
            )
        for i, (e_item, p_item) in enumerate(zip(expected, pred)):
            child = compare_values(
                e_item,
                p_item,
                key_name=key_name,
                path=f"{path}[{i}]",
                float_tol=float_tol,
            )
            if not child.ok:
                return child
        return CompareResult(True)

    if isinstance(expected, dict):
        if isinstance(pred, str):
            parsed, ok = _try_parse_container(pred)
            if ok and isinstance(parsed, dict):
                pred = parsed
        if not isinstance(pred, dict):
            return CompareResult(False, f"{path}: type_mismatch expected=dict got={type(pred).__name__}")
        # Flexible matching: require all expected keys, ignore extra predicted keys.
        missing = [k for k in expected.keys() if k not in pred]
        if missing:
            return CompareResult(False, f"{path}: missing_keys={missing}")
        for k, e_val in expected.items():
            child = compare_values(
                e_val,
                pred[k],
                key_name=k,
                path=f"{path}.{k}" if path != "$" else f"$.{k}",
                float_tol=float_tol,
            )
            if not child.ok:
                return child
        return CompareResult(True)

    # D1 fidelity: a number / bool / None rendered as a string ('282', 'true',
    # 'null', '8.0'). Coerce and require the *value* to be equal -- '8' will not
    # match an expected 9, so this forgives only the type, not a wrong number.
    if isinstance(pred, str) and not isinstance(expected, (str, list, dict)):
        cv, ok = _coerce_scalar_string(pred)
        if ok:
            if isinstance(expected, bool):
                if isinstance(cv, bool) and cv == expected:
                    return CompareResult(True)
            elif expected is None:
                if cv is None:
                    return CompareResult(True)
            elif is_number(expected) and is_number(cv):
                if math.isclose(float(expected), float(cv), rel_tol=float_tol, abs_tol=float_tol):
                    return CompareResult(True)

    if expected == pred:
        return CompareResult(True)
    return CompareResult(False, f"{path}: value_mismatch {expected!r} != {pred!r}")


def pct(part: int, whole: int) -> float:
    return 0.0 if whole == 0 else (part / whole) * 100.0


def has_prediction_dirs(pred_repo_root: Path) -> bool:
    if not pred_repo_root.exists() or not pred_repo_root.is_dir():
        return False
    for p in pred_repo_root.iterdir():
        if p.is_dir() and (p / "answer.json").exists():
            return True
    return False


def discover_repos_for_scope(eval_root: Path, tool: str, model: str, vendor: Optional[str]) -> Tuple[Path, List[str]]:
    if tool.lower() == "llm":
        if not vendor:
            raise SystemExit("For --tool llm when evaluating all repos, pass --vendor (e.g. --vendor openai).")
        model_root = eval_root / "llm" / vendor.lower() / model
    else:
        model_root = eval_root / tool / model

    if not model_root.exists() or not model_root.is_dir():
        return model_root, []

    repos = [p.name for p in model_root.iterdir() if p.is_dir() and has_prediction_dirs(p)]
    return model_root, sorted(repos)


def discover_instance_names(qa_repo_root: Path, pred_repo_root: Path) -> List[str]:
    names = set()

    if qa_repo_root.exists():
        for p in qa_repo_root.iterdir():
            if not p.is_dir():
                continue
            # qa_instances_eval instances generally contain question.json (no oracle.json).
            if (p / "question.json").exists() or (p / "oracle.json").exists():
                names.add(p.name)

    if pred_repo_root.exists():
        for p in pred_repo_root.iterdir():
            if p.is_dir() and (p / "answer.json").exists():
                names.add(p.name)

    return sorted(names)


def strict_oracle_path(repo: str, instance: str) -> Path:
    return REPO_ROOT / "qa_instances" / repo / instance / "oracle.json"


def resolve_prediction_root(eval_root: Path, tool: str, model: str, repo: str, vendor: Optional[str]) -> Path:
    # New layout for host LLM runs: evaluations/llm/<vendor>/<model>/<repo>
    if tool.lower() == "llm":
        if vendor:
            return eval_root / "llm" / vendor.lower() / model / repo

        # Best-effort fallback: auto-detect vendor if omitted.
        llm_root = eval_root / "llm"
        if llm_root.exists():
            candidates = sorted(
                p / model / repo
                for p in llm_root.iterdir()
                if p.is_dir() and (p / model / repo).exists()
            )
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                matches = ", ".join(str(p.parent.name) for p in candidates)
                raise SystemExit(
                    f"Multiple vendors match model/repo under {llm_root}: {matches}. "
                    "Please pass --vendor."
                )
        raise SystemExit("For --tool llm, pass --vendor (e.g. --vendor openai).")

    # Legacy layout for existing non-LLM tools.
    return eval_root / tool / model / repo


def discover_all_targets(eval_root: Path) -> List[EvalTarget]:
    targets: List[EvalTarget] = []
    if not eval_root.exists():
        return targets

    for tool_dir in sorted(p for p in eval_root.iterdir() if p.is_dir()):
        tool = tool_dir.name
        if tool.lower() == "llm":
            for vendor_dir in sorted(p for p in tool_dir.iterdir() if p.is_dir()):
                for model_dir in sorted(p for p in vendor_dir.iterdir() if p.is_dir()):
                    for repo_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
                        if has_prediction_dirs(repo_dir):
                            targets.append(
                                EvalTarget(
                                    tool="llm",
                                    vendor=vendor_dir.name.lower(),
                                    model=model_dir.name,
                                    repo=repo_dir.name,
                                )
                            )
            continue

        for model_dir in sorted(p for p in tool_dir.iterdir() if p.is_dir()):
            for repo_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
                if has_prediction_dirs(repo_dir):
                    targets.append(
                        EvalTarget(
                            tool=tool,
                            model=model_dir.name,
                            repo=repo_dir.name,
                        )
                    )

    return targets


def merge_stats(dst: EvalStats, src: EvalStats) -> None:
    dst.total += src.total
    dst.correct += src.correct
    dst.invalid_pred += src.invalid_pred
    dst.missing_pred += src.missing_pred
    dst.missing_oracle += src.missing_oracle
    for kind, val in src.per_kind_total.items():
        dst.per_kind_total[kind] = dst.per_kind_total.get(kind, 0) + val
    for kind, val in src.per_kind_correct.items():
        dst.per_kind_correct[kind] = dst.per_kind_correct.get(kind, 0) + val
    dst.failed_instances.extend(src.failed_instances)


def aggregate_results(results: List[Tuple[EvalTarget, EvalStats]]) -> EvalStats:
    aggregate = EvalStats()
    for _, stats in results:
        merge_stats(aggregate, stats)
    return aggregate


def filter_excel_results(results: List[Tuple[EvalTarget, EvalStats]]) -> List[Tuple[EvalTarget, EvalStats]]:
    return [
        (target, stats)
        for target, stats in results
        if target.tool.lower() not in EXCEL_EXCLUDED_TOOLS
    ]


def evaluate_target(
    *,
    target: EvalTarget,
    qa_root: Path,
    eval_root: Path,
    float_tol: float,
    require_prediction_root: bool,
) -> EvalStats:
    qa_repo_root = qa_root / target.repo
    oracle_repo_root = REPO_ROOT / "qa_instances" / target.repo
    pred_repo_root = resolve_prediction_root(
        eval_root=eval_root,
        tool=target.tool,
        model=target.model,
        repo=target.repo,
        vendor=target.vendor,
    )

    if not qa_repo_root.exists():
        raise SystemExit(f"QA repo directory not found: {qa_repo_root}")
    if not oracle_repo_root.exists():
        raise SystemExit(f"Oracle repo directory not found: {oracle_repo_root}")
    if require_prediction_root and not pred_repo_root.exists():
        raise SystemExit(f"Prediction repo directory not found: {pred_repo_root}")

    instance_names = discover_instance_names(qa_repo_root, pred_repo_root)

    stats = EvalStats(total=len(instance_names))
    for instance in instance_names:
        oracle_path = strict_oracle_path(target.repo, instance)
        pred_path = pred_repo_root / instance / "answer.json"

        if not oracle_path.exists():
            stats.missing_oracle += 1
            stats.failed_instances.append((target.repo, instance, "missing_oracle_json"))
            continue

        try:
            oracle = load_json(oracle_path)
        except Exception as exc:
            stats.failed_instances.append((target.repo, instance, f"invalid_oracle_json: {exc}"))
            continue

        kind = str(oracle.get("question_kind", "unknown"))
        stats.per_kind_total[kind] = stats.per_kind_total.get(kind, 0) + 1
        oracle_answer = oracle.get("oracle_answer")

        if not pred_path.exists():
            stats.missing_pred += 1
            stats.failed_instances.append((target.repo, instance, "missing_answer_json"))
            continue

        try:
            pred_raw = load_json(pred_path)
            pred_answer = pick_answer_payload(pred_raw)
        except Exception as exc:
            stats.invalid_pred += 1
            stats.failed_instances.append((target.repo, instance, f"invalid_pred_json: {exc}"))
            continue

        cmp_res = compare_values(
            expected=oracle_answer,
            pred=pred_answer,
            key_name="root",
            path="$",
            float_tol=float_tol,
        )
        if cmp_res.ok:
            stats.correct += 1
            stats.per_kind_correct[kind] = stats.per_kind_correct.get(kind, 0) + 1
        else:
            stats.failed_instances.append((target.repo, instance, cmp_res.reason or "mismatch"))

    return stats


def print_summary(scope_lines: List[str], stats: EvalStats) -> None:
    print("Summary")
    for line in scope_lines:
        print(line)
    print(f"total_instances: {stats.total}")
    print(f"overall_accuracy: {pct(stats.correct, stats.total):.2f}% ({stats.correct}/{stats.total})")
    print(f"missing_predictions: {stats.missing_pred}")
    print(f"missing_oracles: {stats.missing_oracle}")
    print(f"invalid_predictions: {stats.invalid_pred}")


def print_per_kind_accuracy(stats: EvalStats) -> None:
    print("\nPer-kind accuracy")
    if not stats.per_kind_total:
        print("none")
        return
    for kind in sorted(stats.per_kind_total.keys()):
        k_total = stats.per_kind_total[kind]
        k_correct = stats.per_kind_correct.get(kind, 0)
        print(f"{kind}: {pct(k_correct, k_total):.2f}% ({k_correct}/{k_total})")


def print_failed_instances(stats: EvalStats, single_repo: Optional[str]) -> None:
    print("\nFailed instances")
    if not stats.failed_instances:
        print("none")
        return
    for repo, instance, reason in sorted(stats.failed_instances, key=lambda x: (x[0], x[1])):
        if single_repo and repo == single_repo:
            print(f"- {instance}: {reason}")
        else:
            print(f"- {repo}/{instance}: {reason}")


def write_excel(
    path: Path,
    *,
    scope_lines: List[str],
    results: List[Tuple[EvalTarget, EvalStats]],
    aggregate: EvalStats,
    qa_root: Path,
) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise SystemExit(
            "openpyxl is required for --excel. Install with: pip install openpyxl"
        ) from exc

    results = filter_excel_results(results)
    aggregate = aggregate_results(results)

    bold = Font(bold=True)
    wb = Workbook()

    def autosize(ws, max_width: int = 60) -> None:
        for col_cells in ws.columns:
            length = 0
            letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                v = cell.value
                if v is None:
                    continue
                length = max(length, len(str(v)))
            ws.column_dimensions[letter].width = min(max(length + 2, 10), max_width)

    # Summary
    ws = wb.active
    ws.title = "Summary"
    row = 1
    for line in scope_lines:
        ws.cell(row=row, column=1, value=line).font = bold
        row += 1
    row += 1
    summary_rows = [
        ("total_instances", aggregate.total),
        ("correct", aggregate.correct),
        ("overall_accuracy_pct", round(pct(aggregate.correct, aggregate.total), 2)),
        ("missing_oracles", aggregate.missing_oracle),
        ("invalid_predictions", aggregate.invalid_pred),
    ]
    for label, value in summary_rows:
        ws.cell(row=row, column=1, value=label).font = bold
        ws.cell(row=row, column=2, value=value)
        row += 1
    autosize(ws)

    # PerTarget
    ws2 = wb.create_sheet("PerTarget")
    headers = [
        "tool", "vendor", "model", "repo",
        "total", "correct", "accuracy_pct",
        "missing_oracle", "invalid_pred",
    ]
    for col, h in enumerate(headers, start=1):
        ws2.cell(row=1, column=col, value=h).font = bold
    for i, (target, stats) in enumerate(sorted(results, key=lambda x: x[0].label()), start=2):
        ws2.cell(row=i, column=1, value=target.tool)
        ws2.cell(row=i, column=2, value=target.vendor or "")
        ws2.cell(row=i, column=3, value=target.model)
        ws2.cell(row=i, column=4, value=target.repo)
        ws2.cell(row=i, column=5, value=stats.total)
        ws2.cell(row=i, column=6, value=stats.correct)
        ws2.cell(row=i, column=7, value=round(pct(stats.correct, stats.total), 2))
        ws2.cell(row=i, column=8, value=stats.missing_oracle)
        ws2.cell(row=i, column=9, value=stats.invalid_pred)
    autosize(ws2)

    # PerToolModel — averaged across all repos for each (tool, vendor, model)
    ws_avg = wb.create_sheet("PerToolModel")
    headers = [
        "tool", "vendor", "model",
        "repos", "total", "correct", "accuracy_pct",
        "missing_oracle", "invalid_pred",
    ]
    for col, h in enumerate(headers, start=1):
        ws_avg.cell(row=1, column=col, value=h).font = bold
    grouped: Dict[Tuple[str, str, str], Dict[str, int]] = {}
    for target, stats in results:
        key = (target.tool, target.vendor or "", target.model)
        g = grouped.setdefault(
            key,
            {"repos": 0, "total": 0, "correct": 0, "missing_oracle": 0, "invalid_pred": 0},
        )
        g["repos"] += 1
        g["total"] += stats.total
        g["correct"] += stats.correct
        g["missing_oracle"] += stats.missing_oracle
        g["invalid_pred"] += stats.invalid_pred
    for i, (key, g) in enumerate(sorted(grouped.items()), start=2):
        tool, vendor_name, model = key
        ws_avg.cell(row=i, column=1, value=tool)
        ws_avg.cell(row=i, column=2, value=vendor_name)
        ws_avg.cell(row=i, column=3, value=model)
        ws_avg.cell(row=i, column=4, value=g["repos"])
        ws_avg.cell(row=i, column=5, value=g["total"])
        ws_avg.cell(row=i, column=6, value=g["correct"])
        ws_avg.cell(row=i, column=7, value=round(pct(g["correct"], g["total"]), 2))
        ws_avg.cell(row=i, column=8, value=g["missing_oracle"])
        ws_avg.cell(row=i, column=9, value=g["invalid_pred"])
    autosize(ws_avg)

    # PerToolModelPerKind — per question kind, aggregated across all repos for each (tool, vendor, model)
    ws_tmk = wb.create_sheet("PerToolModelPerKind")
    headers = [
        "tool", "vendor", "model", "question_kind",
        "total", "correct", "accuracy_pct",
    ]
    for col, h in enumerate(headers, start=1):
        ws_tmk.cell(row=1, column=col, value=h).font = bold
    per_tool_model_kind: Dict[Tuple[str, str, str, str], Dict[str, int]] = {}
    for target, stats in results:
        for kind, k_total in stats.per_kind_total.items():
            key = (target.tool, target.vendor or "", target.model, kind)
            g = per_tool_model_kind.setdefault(key, {"total": 0, "correct": 0})
            g["total"] += k_total
            g["correct"] += stats.per_kind_correct.get(kind, 0)
    for row, (key, g) in enumerate(sorted(per_tool_model_kind.items()), start=2):
        tool, vendor_name, model, kind = key
        ws_tmk.cell(row=row, column=1, value=tool)
        ws_tmk.cell(row=row, column=2, value=vendor_name)
        ws_tmk.cell(row=row, column=3, value=model)
        ws_tmk.cell(row=row, column=4, value=kind)
        ws_tmk.cell(row=row, column=5, value=g["total"])
        ws_tmk.cell(row=row, column=6, value=g["correct"])
        ws_tmk.cell(row=row, column=7, value=round(pct(g["correct"], g["total"]), 2))
    autosize(ws_tmk)

    # PerKind (aggregate by tool, so all LLM vendors/models stay together)
    ws3 = wb.create_sheet("PerKind")
    headers = ["tool", "question_kind", "total", "correct", "accuracy_pct"]
    for col, h in enumerate(headers, start=1):
        ws3.cell(row=1, column=col, value=h).font = bold
    per_kind_grouped: Dict[Tuple[str, str], Dict[str, int]] = {}
    for target, stats in results:
        for kind, k_total in stats.per_kind_total.items():
            key = (target.tool, kind)
            g = per_kind_grouped.setdefault(key, {"total": 0, "correct": 0})
            g["total"] += k_total
            g["correct"] += stats.per_kind_correct.get(kind, 0)
    for row, (key, g) in enumerate(sorted(per_kind_grouped.items()), start=2):
        tool, kind = key
        ws3.cell(row=row, column=1, value=tool)
        ws3.cell(row=row, column=2, value=kind)
        ws3.cell(row=row, column=3, value=g["total"])
        ws3.cell(row=row, column=4, value=g["correct"])
        ws3.cell(row=row, column=5, value=round(pct(g["correct"], g["total"]), 2))
    autosize(ws3)

    # PerTargetPerKind
    ws5 = wb.create_sheet("PerTargetPerKind")
    headers = [
        "tool", "vendor", "model", "repo", "question_kind",
        "total", "correct", "accuracy_pct",
    ]
    for col, h in enumerate(headers, start=1):
        ws5.cell(row=1, column=col, value=h).font = bold
    row = 2
    for target, stats in sorted(results, key=lambda x: x[0].label()):
        for kind in sorted(stats.per_kind_total.keys()):
            k_total = stats.per_kind_total[kind]
            k_correct = stats.per_kind_correct.get(kind, 0)
            ws5.cell(row=row, column=1, value=target.tool)
            ws5.cell(row=row, column=2, value=target.vendor or "")
            ws5.cell(row=row, column=3, value=target.model)
            ws5.cell(row=row, column=4, value=target.repo)
            ws5.cell(row=row, column=5, value=kind)
            ws5.cell(row=row, column=6, value=k_total)
            ws5.cell(row=row, column=7, value=k_correct)
            ws5.cell(row=row, column=8, value=round(pct(k_correct, k_total), 2))
            row += 1
    autosize(ws5)

    # QuestionKinds — total question_kind counts across all repos
    # (mirrors the "ALL REPOS" section of `python count_question_kinds.py all`).
    ws6 = wb.create_sheet("QuestionKinds")
    headers = ["question_kind", "count"]
    for col, h in enumerate(headers, start=1):
        ws6.cell(row=1, column=col, value=h).font = bold
    row = 2
    qa_base = qa_root if qa_root.exists() else REPO_ROOT / "qa_instances"
    grand_total: Counter[str] = Counter()
    if qa_base.exists():
        for repo_dir in sorted(p for p in qa_base.iterdir() if p.is_dir()):
            grand_total.update(count_question_kinds(repo_dir))
    for kind, count in grand_total.most_common():
        ws6.cell(row=row, column=1, value=kind)
        ws6.cell(row=row, column=2, value=count)
        row += 1
    ws6.cell(row=row, column=1, value="TOTAL").font = bold
    ws6.cell(row=row, column=2, value=sum(grand_total.values())).font = bold
    autosize(ws6)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def print_target_accuracies(title: str, results: List[Tuple[EvalTarget, EvalStats]], repo_only: bool = False) -> None:
    print(f"\n{title}")
    if not results:
        print("none")
        return
    for target, stats in sorted(results, key=lambda x: x[0].label()):
        label = target.repo if repo_only else target.label()
        print(f"{label}: {pct(stats.correct, stats.total):.2f}% ({stats.correct}/{stats.total})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate QA answers against oracles")
    parser.add_argument("--tool", help="Tool name under evaluations/ (e.g. cursor)")
    parser.add_argument(
        "--vendor",
        default=None,
        help="Vendor name for --tool llm (e.g. openai, gemini, anthropic, vllm)",
    )
    parser.add_argument("--model", help="Model name under evaluations/<tool>/ (or evaluations/llm/<vendor>/ for --tool llm)")
    parser.add_argument(
        "--repo",
        help="Repository name (e.g. Sympy). Omit or use 'all' to evaluate all repos under the selected tool/model scope.",
    )
    parser.add_argument("--all", action="store_true", help="Aggregate all available results across all tools/vendors/models/repos.")
    parser.add_argument("--qa-root", default=str(REPO_ROOT / "qa_instances"))
    parser.add_argument("--eval-root", default=str(REPO_ROOT / "evaluations"))
    parser.add_argument("--float-tol", type=float, default=1e-6)
    parser.add_argument(
        "--excel",
        nargs="?",
        const="evaluation_results.xlsx",
        default=None,
        help="Write results to an Excel file. Pass a path to override the default 'evaluation_results.xlsx'.",
    )
    args = parser.parse_args()

    qa_root = Path(args.qa_root).resolve()
    eval_root = Path(args.eval_root).resolve()
    vendor = args.vendor.lower() if args.vendor else None

    if args.all and any([args.tool, args.vendor, args.model, args.repo]):
        parser.error("--all cannot be combined with --tool/--vendor/--model/--repo.")

    if args.excel:
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            raise SystemExit(
                "openpyxl is required for --excel. Install with: "
                f"{Path(__import__('sys').executable).name} -m pip install openpyxl"
            )

    if args.all:
        targets = discover_all_targets(eval_root)
        if not targets:
            raise SystemExit(f"No evaluation targets found under {eval_root}")

        results: List[Tuple[EvalTarget, EvalStats]] = []
        skipped: List[Tuple[EvalTarget, str]] = []
        aggregate = EvalStats()

        for target in targets:
            try:
                stats = evaluate_target(
                    target=target,
                    qa_root=qa_root,
                    eval_root=eval_root,
                    float_tol=args.float_tol,
                    require_prediction_root=True,
                )
                results.append((target, stats))
                merge_stats(aggregate, stats)
            except SystemExit as exc:
                skipped.append((target, str(exc)))

        print_summary(
            scope_lines=[
                "scope: all",
                f"targets_evaluated: {len(results)}",
                f"targets_skipped: {len(skipped)}",
            ],
            stats=aggregate,
        )
        print_target_accuracies("Per-target accuracy", results, repo_only=False)
        print_per_kind_accuracy(aggregate)
        print_failed_instances(aggregate, single_repo=None)

        if skipped:
            print("\nSkipped targets")
            for target, reason in sorted(skipped, key=lambda x: x[0].label()):
                print(f"- {target.label()}: {reason}")

        if args.excel:
            excel_path = Path(args.excel).resolve()
            write_excel(
                excel_path,
                scope_lines=[
                    "scope: all",
                    f"targets_evaluated: {len(results)}",
                    f"targets_skipped: {len(skipped)}",
                ],
                results=results,
                aggregate=aggregate,
                qa_root=qa_root,
            )
            print(f"\nExcel report written to: {excel_path}")
        return

    if not args.tool or not args.model:
        parser.error("When --all is not set, --tool and --model are required.")

    repo_selector = args.repo or "all"

    if repo_selector.lower() == "all":
        scope_root, repos = discover_repos_for_scope(
            eval_root=eval_root,
            tool=args.tool,
            model=args.model,
            vendor=vendor,
        )
        if not repos:
            raise SystemExit(f"No repositories with predictions found under {scope_root}")

        results: List[Tuple[EvalTarget, EvalStats]] = []
        skipped: List[Tuple[EvalTarget, str]] = []
        aggregate = EvalStats()
        for repo in repos:
            target = EvalTarget(tool=args.tool, vendor=vendor, model=args.model, repo=repo)
            try:
                stats = evaluate_target(
                    target=target,
                    qa_root=qa_root,
                    eval_root=eval_root,
                    float_tol=args.float_tol,
                    require_prediction_root=True,
                )
                results.append((target, stats))
                merge_stats(aggregate, stats)
            except SystemExit as exc:
                skipped.append((target, str(exc)))

        summary_lines = [f"tool: {args.tool}"]
        if vendor:
            summary_lines.append(f"vendor: {vendor}")
        summary_lines.extend(
            [
                f"model: {args.model}",
                "repo: all",
                f"repos_evaluated: {len(results)}",
                f"repos_skipped: {len(skipped)}",
            ]
        )
        print_summary(scope_lines=summary_lines, stats=aggregate)
        print_target_accuracies("Per-repo accuracy", results, repo_only=True)
        print_per_kind_accuracy(aggregate)
        print_failed_instances(aggregate, single_repo=None)

        if skipped:
            print("\nSkipped repos")
            for target, reason in sorted(skipped, key=lambda x: x[0].repo):
                print(f"- {target.repo}: {reason}")

        if args.excel:
            excel_path = Path(args.excel).resolve()
            write_excel(
                excel_path,
                scope_lines=summary_lines,
                results=results,
                aggregate=aggregate,
                qa_root=qa_root,
            )
            print(f"\nExcel report written to: {excel_path}")
        return

    target = EvalTarget(tool=args.tool, vendor=vendor, model=args.model, repo=repo_selector)
    stats = evaluate_target(
        target=target,
        qa_root=qa_root,
        eval_root=eval_root,
        float_tol=args.float_tol,
        require_prediction_root=True,
    )

    summary_lines = [f"tool: {args.tool}"]
    if vendor:
        summary_lines.append(f"vendor: {vendor}")
    summary_lines.extend([f"model: {args.model}", f"repo: {repo_selector}"])
    print_summary(scope_lines=summary_lines, stats=stats)
    print_per_kind_accuracy(stats)
    print_failed_instances(stats, single_repo=repo_selector)

    if args.excel:
        excel_path = Path(args.excel).resolve()
        write_excel(
            excel_path,
            scope_lines=summary_lines,
            results=[(target, stats)],
            aggregate=stats,
            qa_root=qa_root,
        )
        print(f"\nExcel report written to: {excel_path}")


if __name__ == "__main__":
    main()
