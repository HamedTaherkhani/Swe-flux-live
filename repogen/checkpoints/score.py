"""Score a solver's checkpoint answers against a derived spec and summarise
them as a ladder: the first level a solver fails locates where its account of
the execution stops agreeing with the real one."""

from __future__ import annotations

import ast
import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .derive import LEVELS

ANSWER_LEVEL = "answer"
LADDER = tuple(LEVELS) + (ANSWER_LEVEL,)
_MISSING = object()


def _lookup(answer: Any, path: List[str]) -> Any:
    node = answer
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _canonical(value: Any) -> Any:
    """Tuples and lists are not distinguished: a solver that has the right
    elements in the right order has tracked the state."""
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {"__set__": sorted((repr(_canonical(v)) for v in value))}
    if isinstance(value, dict):
        return {repr(_canonical(k)): _canonical(v) for k, v in value.items()}
    return value


def _same(expected: Any, predicted: Any, tol: float) -> bool:
    if isinstance(expected, bool) or isinstance(predicted, bool):
        return type(expected) is type(predicted) and expected == predicted
    if isinstance(expected, (int, float)) and isinstance(predicted, (int, float)):
        return math.isclose(float(expected), float(predicted), rel_tol=tol, abs_tol=tol)
    if isinstance(expected, list) and isinstance(predicted, list):
        return len(expected) == len(predicted) and all(
            _same(e, p, tol) for e, p in zip(expected, predicted)
        )
    if isinstance(expected, dict) and isinstance(predicted, dict):
        return expected.keys() == predicted.keys() and all(
            _same(expected[k], predicted[k], tol) for k in expected
        )
    return type(expected) is type(predicted) and expected == predicted


def _value_candidates(predicted: Any) -> Iterable[Any]:
    if isinstance(predicted, str):
        try:
            yield ast.literal_eval(predicted.strip())
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            pass
    # A bare string is also accepted as the string value itself, and a JSON
    # value as the Python value it denotes.
    yield predicted


def _fold(line: int, fold: Dict[str, int]) -> int:
    return int(fold.get(str(line), line))


def score_checkpoint(checkpoint: dict, answer: Any, *, float_tol: float = 1e-6) -> dict:
    predicted = _lookup(answer, checkpoint["path"])
    expected = checkpoint["expected"]
    kind = checkpoint["kind"]
    result = {
        "id": checkpoint["id"],
        "level": checkpoint["level"],
        "kind": kind,
        "answered": predicted is not _MISSING,
        "score": 0.0,
    }
    if predicted is _MISSING:
        return result
    result["predicted"] = predicted

    if kind == "int":
        value = _as_int(predicted)
        accept = checkpoint.get("accept") or [expected]
        result["score"] = 1.0 if value is not None and value in accept else 0.0
    elif kind == "line":
        value = _as_int(predicted)
        if value is not None:
            folded = _fold(value, checkpoint.get("fold") or {})
            accept = checkpoint.get("accept") or [expected]
            result["score"] = 1.0 if folded in accept else 0.0
    elif kind == "line_set":
        fold = checkpoint.get("fold") or {}
        ignore = set(checkpoint.get("ignore") or [])
        raw = predicted if isinstance(predicted, list) else []
        given = {_fold(v, fold) for v in (_as_int(item) for item in raw) if v is not None}
        given -= ignore
        wanted = set(expected)
        hits = len(given & wanted)
        precision = hits / len(given) if given else 0.0
        recall = hits / len(wanted) if wanted else 0.0
        result["precision"] = round(precision, 4)
        result["recall"] = round(recall, 4)
        result["score"] = (
            round(2 * precision * recall / (precision + recall), 4) if hits else 0.0
        )
        if given == wanted:
            result["score"] = 1.0
    elif kind == "enum":
        result["score"] = 1.0 if str(predicted).strip().lower() == str(expected).lower() else 0.0
    elif kind == "name":
        given_name = str(predicted).strip().rpartition(".")[2]
        result["score"] = 1.0 if given_name == str(expected) else 0.0
    elif kind == "value":
        wanted_value = _canonical(ast.literal_eval(expected))
        if any(
            _same(wanted_value, _canonical(candidate), float_tol)
            for candidate in _value_candidates(predicted)
        ):
            result["score"] = 1.0
    else:
        raise ValueError(f"unknown checkpoint kind: {kind}")
    return result


def score_instance(
    spec: dict,
    answer: Any,
    *,
    final_correct: Optional[bool] = None,
    float_tol: float = 1e-6,
) -> dict:
    """Score every checkpoint and fold them into per-level results. A level
    passes only when all of its checkpoints are exactly right; its score is
    their mean, which keeps partial credit visible."""
    results = [score_checkpoint(c, answer, float_tol=float_tol) for c in spec["checkpoints"]]
    levels: Dict[str, dict] = {}
    for level in LEVELS:
        mine = [r for r in results if r["level"] == level]
        if not mine:
            continue
        levels[level] = {
            "checkpoints": len(mine),
            "answered": sum(1 for r in mine if r["answered"]),
            "correct": sum(1 for r in mine if r["score"] >= 1.0),
            "score": round(sum(r["score"] for r in mine) / len(mine), 4),
            "passed": all(r["score"] >= 1.0 for r in mine),
        }
    if final_correct is not None:
        levels[ANSWER_LEVEL] = {
            "checkpoints": 1, "answered": 1, "correct": int(final_correct),
            "score": 1.0 if final_correct else 0.0, "passed": bool(final_correct),
        }

    order = [level for level in LADDER if level in levels]
    pattern = [levels[level]["passed"] for level in order]
    first_failed = next((level for level in order if not levels[level]["passed"]), None)
    depth = 0
    for passed in pattern:
        if not passed:
            break
        depth += 1
    return {
        "instance_id": spec["instance_id"],
        "category": spec.get("category", ""),
        "answered": any(r["answered"] for r in results),
        "levels": levels,
        "ladder": order,
        "depth": depth,
        "first_failed_level": first_failed,
        # A pass above a failed level means the levels did not behave as a
        # hierarchy for this instance.
        "monotone": all(not later for later in pattern[depth:]),
        "final_correct": final_correct,
        "checkpoints": results,
    }


def _level_table(rows: List[dict]) -> Dict[str, dict]:
    table: Dict[str, dict] = {}
    for level in LADDER:
        mine = [row["levels"][level] for row in rows if level in row["levels"]]
        if not mine:
            continue
        table[level] = {
            "instances": len(mine),
            "passed": sum(1 for item in mine if item["passed"]),
            "pass_rate": round(sum(1 for item in mine if item["passed"]) / len(mine), 4),
            "mean_score": round(sum(item["score"] for item in mine) / len(mine), 4),
        }
    return table


def _first_failure(rows: List[dict]) -> Dict[str, int]:
    counts = Counter(row["first_failed_level"] or "none" for row in rows)
    return {key: counts[key] for key in LADDER + ("none",) if counts.get(key)}


def summarise(rows: List[dict]) -> dict:
    """Aggregate instance ladders. Instances whose solver returned no
    checkpoint answer are reported separately instead of being scored as zero."""
    answered = [row for row in rows if row["answered"]]
    by_category: Dict[str, List[dict]] = defaultdict(list)
    for row in answered:
        by_category[row.get("category") or "unknown"].append(row)

    def block(subset: List[dict]) -> dict:
        return {
            "instances": len(subset),
            "levels": _level_table(subset),
            "first_failed_level": _first_failure(subset),
            "mean_depth": round(sum(r["depth"] for r in subset) / len(subset), 4) if subset else 0.0,
        }

    scored_final = [row for row in answered if row["final_correct"] is not None]
    return {
        "instances": len(rows),
        "answered": len(answered),
        "unanswered": len(rows) - len(answered),
        "overall": block(answered),
        "by_final_answer": {
            "correct": block([r for r in scored_final if r["final_correct"]]),
            "wrong": block([r for r in scored_final if not r["final_correct"]]),
        },
        "by_category": {name: block(subset) for name, subset in sorted(by_category.items())},
        "consistency": {
            "monotone_instances": sum(1 for r in answered if r["monotone"]),
            "monotone_rate": round(
                sum(1 for r in answered if r["monotone"]) / len(answered), 4
            ) if answered else 0.0,
            "correct_answer_with_failed_checkpoint": sum(
                1 for r in scored_final
                if r["final_correct"] and r["first_failed_level"] not in (None, ANSWER_LEVEL)
            ),
        },
    }

