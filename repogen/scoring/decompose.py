"""Answer error decomposition: partial credit and an error label for answers
the binary comparison rejects.

The binary scorer stops at the first mismatch. This module compares the whole
answer and separates *what* was identified (lines, functions, variables) from
*how much* was measured (counts, values), so a wrong answer can be read as
"right structure, wrong counts" or "path diverged at step k".

Metrics are chosen by the shape of each answer field, not by question
category, because one category produces several shapes and one shape serves
several categories:

  scalar_number   exact match and relative error
  scalar_other    exact match (bool / string)
  set             precision, recall, F1 over elements
  sequence        common prefix, order-aware similarity, order-free F1
  keyed_records   F1 over record identities, accuracy of measured values

Every leaf is compared with the benchmark's own `compare_values`, so path,
identifier and number normalisation are identical to the binary score, and an
answer the binary scorer accepts always scores 1.0.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .evaluate_qa_answers import (
    ORDER_INSENSITIVE_LIST_KEYS,
    _try_parse_container,
    compare_values,
    is_number,
    pick_answer_payload,
)

SCHEMA_VERSION = 1

# Record fields that hold a measurement. Every other scalar field of a record
# identifies what the record is about. Types cannot decide this: `def_line`
# and `count` are both integers.
MEASURE_FIELDS = {
    "count", "observations", "violations", "held_always", "value", "values",
    "iterations", "inner_iterations", "invocations", "total",
    "message", "exception_message", "handled", "handled_where",
    "caller_saw_exception",
}

# Beyond this many cell comparisons the order-aware similarity is skipped; the
# prefix and the order-free F1 are still reported.
SEQUENCE_CELL_LIMIT = 40_000_000

# Most structural problem first: an instance takes the first label that any of
# its fields has.
LABEL_PRIORITY = (
    "invalid", "missing_field", "wrong_elements", "missing_elements",
    "extra_elements", "diverged", "truncated", "order_only",
    "values_wrong", "counts_wrong", "scalar_wrong", "format_only", "correct",
)


# --------------------------------------------------------------------------
# Element matching
# --------------------------------------------------------------------------


def _token(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _same(expected: Any, predicted: Any, key_name: str, tol: float) -> bool:
    return compare_values(expected, predicted, key_name=key_name, path="$", float_tol=tol).ok


def _same_identity(expected: Any, predicted: Any, key_name: str, tol: float) -> bool:
    if isinstance(expected, dict):
        if not isinstance(predicted, dict):
            return False
        return all(
            field in predicted and _same(expected[field], predicted[field], field, tol)
            for field in expected
        )
    return _same(expected, predicted, key_name, tol)


def _unify(
    expected: List[Any], predicted: List[Any], key_name: str, tol: float
) -> Tuple[List[str], List[str]]:
    """Give equal elements equal tokens. Exact matches are found by hashing;
    only the remaining distinct elements go through the tolerant comparison."""
    expected_tokens = [_token(item) for item in expected]
    known: Dict[str, Any] = {}
    for token, item in zip(expected_tokens, expected):
        known.setdefault(token, item)
    resolved: Dict[str, str] = {}
    predicted_tokens: List[str] = []
    for item in predicted:
        token = _token(item)
        if token not in known and token not in resolved:
            resolved[token] = next(
                (other for other, candidate in known.items()
                 if _same_identity(candidate, item, key_name, tol)),
                token,
            )
        predicted_tokens.append(token if token in known else resolved[token])
    return expected_tokens, predicted_tokens


def _prf(hits: float, predicted: int, expected: int) -> Tuple[float, float, float]:
    precision = hits / predicted if predicted else (1.0 if not expected else 0.0)
    recall = hits / expected if expected else (1.0 if not predicted else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _membership_label(precision: float, recall: float) -> str:
    if precision >= 1.0 and recall >= 1.0:
        return "correct"
    if precision >= 1.0:
        return "missing_elements"
    if recall >= 1.0:
        return "extra_elements"
    return "wrong_elements"


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def _is_scalar(value: Any) -> bool:
    return not isinstance(value, (list, dict))


def _measure_fields(records: List[dict]) -> List[str]:
    fields: List[str] = []
    for record in records:
        for name, value in record.items():
            if name in fields:
                continue
            if name in MEASURE_FIELDS or not _is_scalar(value):
                fields.append(name)
    return fields


def shape_of(key_name: str, expected: Any) -> str:
    if isinstance(expected, bool) or isinstance(expected, str) or expected is None:
        return "scalar_other"
    if is_number(expected):
        return "scalar_number"
    if isinstance(expected, dict):
        if expected and all(_is_scalar(v) for v in expected.values()):
            return "keyed_records"
        return "nested"
    if isinstance(expected, list):
        if all(isinstance(item, dict) for item in expected) and expected:
            if _measure_fields(expected):
                return "keyed_records"
        elif not all(_is_scalar(item) for item in expected):
            return "nested"
        return "set" if key_name in ORDER_INSENSITIVE_LIST_KEYS else "sequence"
    return "scalar_other"


def _result(shape: str, score: float, label: str, **metrics: Any) -> dict:
    score = round(max(0.0, min(1.0, score)), 4)
    return {"shape": shape, "score": score, "label": label, "metrics": metrics}


def _relative_error(expected: float, predicted: float) -> float:
    return abs(float(predicted) - float(expected)) / max(abs(float(expected)), 1.0)


def _score_scalar_number(expected: Any, predicted: Any, key_name: str, tol: float) -> dict:
    if _same(expected, predicted, key_name, tol):
        return _result("scalar_number", 1.0, "correct", relative_error=0.0, signed_error=0)
    try:
        value = float(predicted) if not isinstance(predicted, bool) else None
    except (TypeError, ValueError):
        value = None
    if value is None:
        return _result("scalar_number", 0.0, "invalid")
    error = _relative_error(expected, value)
    # A scalar has no structure to be right about: credit falls with distance.
    return _result(
        "scalar_number", max(0.0, 1.0 - error), "scalar_wrong",
        relative_error=round(error, 4),
        signed_error=value - float(expected),
        off_by_one=abs(value - float(expected)) == 1,
    )


def _score_scalar_other(expected: Any, predicted: Any, key_name: str, tol: float) -> dict:
    ok = _same(expected, predicted, key_name, tol)
    return _result("scalar_other", 1.0 if ok else 0.0, "correct" if ok else "scalar_wrong")


def _score_set(expected: list, predicted: list, key_name: str, tol: float) -> dict:
    expected_tokens, predicted_tokens = _unify(expected, predicted, key_name, tol)
    hits = sum((Counter(expected_tokens) & Counter(predicted_tokens)).values())
    precision, recall, f1 = _prf(hits, len(predicted_tokens), len(expected_tokens))
    return _result(
        "set", f1, _membership_label(precision, recall),
        precision=round(precision, 4), recall=round(recall, 4),
        expected=len(expected_tokens), predicted=len(predicted_tokens),
    )


def _score_sequence(expected: list, predicted: list, key_name: str, tol: float) -> dict:
    expected_tokens, predicted_tokens = _unify(expected, predicted, key_name, tol)
    prefix = 0
    for left, right in zip(expected_tokens, predicted_tokens):
        if left != right:
            break
        prefix += 1
    hits = sum((Counter(expected_tokens) & Counter(predicted_tokens)).values())
    precision, recall, bag_f1 = _prf(hits, len(predicted_tokens), len(expected_tokens))

    similarity: Optional[float] = None
    if expected_tokens == predicted_tokens:
        similarity = 1.0
    elif len(expected_tokens) * len(predicted_tokens) <= SEQUENCE_CELL_LIMIT:
        similarity = difflib.SequenceMatcher(
            None, expected_tokens, predicted_tokens, autojunk=False
        ).ratio()

    if expected_tokens == predicted_tokens:
        label = "correct"
    elif prefix == len(predicted_tokens) and prefix < len(expected_tokens):
        label = "truncated"
    elif Counter(expected_tokens) == Counter(predicted_tokens):
        label = "order_only"
    else:
        label = "diverged"
    return _result(
        "sequence", similarity if similarity is not None else bag_f1, label,
        prefix=prefix,
        prefix_ratio=round(prefix / len(expected_tokens), 4) if expected_tokens else 1.0,
        similarity=round(similarity, 4) if similarity is not None else None,
        bag_f1=round(bag_f1, 4),
        expected=len(expected_tokens), predicted=len(predicted_tokens),
    )


def _as_records(value: Any) -> Optional[List[dict]]:
    if isinstance(value, dict):
        return [{"key": key, "value": item} for key, item in value.items()]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    return None


def _score_keyed(expected: Any, predicted: Any, key_name: str, tol: float) -> dict:
    expected_records = _as_records(expected) or []
    predicted_records = _as_records(predicted)
    if predicted_records is None:
        return _result("keyed_records", 0.0, "invalid")

    measures = ["value"] if isinstance(expected, dict) else _measure_fields(expected_records)
    identity = lambda record: {k: v for k, v in record.items() if k not in measures}  # noqa: E731
    expected_tokens, predicted_tokens = _unify(
        [identity(r) for r in expected_records],
        [identity(r) for r in predicted_records],
        key_name, tol,
    )
    # Records sharing an identity are paired in the order they appear.
    waiting: Dict[str, List[dict]] = defaultdict(list)
    for token, record in zip(predicted_tokens, predicted_records):
        waiting[token].append(record)

    matched = 0
    credit = 0.0
    cells = cells_right = 0
    numeric_errors: List[float] = []
    for token, record in zip(expected_tokens, expected_records):
        if not waiting[token]:
            continue
        other = waiting[token].pop(0)
        matched += 1
        right = 0
        for field in measures:
            if field not in record:
                continue
            cells += 1
            ok = field in other and _same(record[field], other[field], field, tol)
            right += ok
            if is_number(record[field]) and is_number(other.get(field)):
                numeric_errors.append(_relative_error(record[field], other[field]))
        present = sum(1 for field in measures if field in record)
        cells_right += right
        # Half of a record's credit is naming it, half is measuring it.
        credit += 0.5 + 0.5 * (right / present if present else 1.0)

    key_precision, key_recall, key_f1 = _prf(matched, len(predicted_records), len(expected_records))
    _, _, score = _prf(credit, len(predicted_records), len(expected_records))
    value_accuracy = cells_right / cells if cells else 1.0

    if key_f1 < 1.0:
        label = _membership_label(key_precision, key_recall)
    elif value_accuracy < 1.0:
        label = "counts_wrong" if numeric_errors and len(numeric_errors) == cells else "values_wrong"
    elif (
        isinstance(expected, list)
        and key_name not in ORDER_INSENSITIVE_LIST_KEYS
        and expected_tokens != predicted_tokens
    ):
        # Records are matched by identity, so the content can be complete while
        # the positional binary comparison still fails.
        label = "order_only"
    else:
        label = "correct"
    metrics: Dict[str, Any] = {
        "key_precision": round(key_precision, 4),
        "key_recall": round(key_recall, 4),
        "key_f1": round(key_f1, 4),
        "value_accuracy": round(value_accuracy, 4),
        "matched_records": matched,
        "expected": len(expected_records),
        "predicted": len(predicted_records),
    }
    if numeric_errors:
        metrics["median_relative_error"] = round(statistics.median(numeric_errors), 4)
        metrics["max_relative_error"] = round(max(numeric_errors), 4)
    return _result("keyed_records", score, label, **metrics)


def _leaves(value: Any, path: str = "$", key_name: str = "root") -> Iterable[Tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}", key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]", key_name)
    else:
        yield path, key_name, value


def _score_nested(expected: Any, predicted: Any, key_name: str, tol: float) -> dict:
    """Irregular structures are compared leaf by leaf at matching positions."""
    given = {path: value for path, _, value in _leaves(predicted)}
    wanted = list(_leaves(expected))
    right = sum(
        1 for path, name, value in wanted
        if path in given and _same(value, given[path], name, tol)
    )
    precision, recall, f1 = _prf(right, len(given), len(wanted))
    return _result(
        "nested", f1, "correct" if f1 >= 1.0 else "values_wrong",
        precision=round(precision, 4), recall=round(recall, 4),
        expected=len(wanted), predicted=len(given),
    )


_SCORERS = {
    "scalar_number": _score_scalar_number,
    "scalar_other": _score_scalar_other,
    "set": _score_set,
    "sequence": _score_sequence,
    "keyed_records": _score_keyed,
    "nested": _score_nested,
}


def score_field(key_name: str, expected: Any, predicted: Any, *, float_tol: float = 1e-6) -> dict:
    shape = shape_of(key_name, expected)
    if isinstance(expected, (list, dict)):
        if isinstance(predicted, str):
            parsed, ok = _try_parse_container(predicted)
            if ok:
                predicted = parsed
        if type(predicted) is not type(expected):
            return _result(shape, 0.0, "invalid")
    return _SCORERS[shape](expected, predicted, key_name, float_tol)


# --------------------------------------------------------------------------
# Instances and reports
# --------------------------------------------------------------------------


def decompose(oracle_answer: Any, predicted: Any, *, float_tol: float = 1e-6) -> dict:
    """Score one answer. `exact` is the benchmark's binary verdict."""
    payload = pick_answer_payload(predicted)
    exact = compare_values(
        oracle_answer, payload, key_name="root", path="$", float_tol=float_tol
    )
    if isinstance(oracle_answer, dict):
        fields = {}
        for key, expected in oracle_answer.items():
            if not isinstance(payload, dict) or key not in payload:
                fields[key] = _result(shape_of(key, expected), 0.0, "missing_field")
            else:
                fields[key] = score_field(key, expected, payload[key], float_tol=float_tol)
    else:
        fields = {"$": score_field("root", oracle_answer, payload, float_tol=float_tol)}

    labels = {field["label"] for field in fields.values()}
    score = sum(field["score"] for field in fields.values()) / len(fields) if fields else 0.0
    if exact.ok:
        score, label = 1.0, "correct"
        for field in fields.values():
            field["score"], field["label"] = 1.0, "correct"
    elif labels == {"correct"}:
        # Every element is right but the binary scorer still rejects the
        # answer: its position or form differs, not its content.
        label = "format_only"
    else:
        label = next(name for name in LABEL_PRIORITY if name in labels)
    return {
        "exact": exact.ok,
        "exact_reason": exact.reason or "",
        "score": round(score, 4),
        "label": label,
        "shapes": sorted({field["shape"] for field in fields.values()}),
        "fields": fields,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _answer_files(run_dir: Path, source: str) -> Iterable[Tuple[str, str, str, Path]]:
    """Yield (scope, instance_id, rollout, answer path)."""
    if source in ("evaluation", "all"):
        root = run_dir / "evaluation" / "llm"
        for path in sorted(root.glob("*/*/*/answer.json")):
            yield f"{path.parents[2].name}/{path.parents[1].name}", path.parent.name, "", path
        # Static Claude Code and Codex evaluations live beside ``llm/`` under
        # evaluation/<agent>-noexec/<model>/<instance>/answer.json.
        root = run_dir / "evaluation"
        for path in sorted(root.glob("*-noexec/*/*/answer.json")):
            yield f"{path.parents[2].name}/{path.parents[1].name}", path.parent.name, "", path
    if source in ("validation", "all"):
        root = run_dir / "validation" / "solver_agent"
        for path in sorted(root.glob("*/*/*/*/answer.json")):
            scope = f"agent:{path.parents[3].name}/{path.parents[2].name}"
            yield scope, path.parents[1].name, path.parent.name, path


def _reported(run_dir: Path) -> Dict[str, set]:
    report = _read_json(run_dir / "evaluation_report.json")
    seen: Dict[str, set] = defaultdict(set)
    for run in (report or {}).get("runs", []) if isinstance(report, dict) else []:
        for verdict in run.get("verdicts", []):
            seen[run.get("scope", "")].add(verdict.get("instance_id", ""))
    return seen


def _summary(rows: List[dict]) -> dict:
    if not rows:
        return {"answers": 0}
    failed = [row for row in rows if not row["exact"]]
    labels = Counter(row["label"] for row in rows)
    out = {
        "answers": len(rows),
        "not_in_evaluation_report": sum(1 for row in rows if row.get("reported") is False),
        "exact": len(rows) - len(failed),
        "exact_rate": round((len(rows) - len(failed)) / len(rows), 4),
        "mean_score": round(sum(row["score"] for row in rows) / len(rows), 4),
        "labels": {name: labels[name] for name in LABEL_PRIORITY if labels.get(name)},
    }
    if failed:
        scores = [row["score"] for row in failed]
        out["failed"] = {
            "answers": len(failed),
            "mean_score": round(sum(scores) / len(scores), 4),
            "median_score": round(statistics.median(scores), 4),
            "score_at_least": {
                str(level): sum(1 for value in scores if value >= level)
                for level in (0.5, 0.8, 0.9, 0.95)
            },
        }
    return out


def _group(rows: List[dict], key) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        for name in key(row):
            groups[name].append(row)
    return {name: _summary(members) for name, members in sorted(groups.items())}


def _field_summary(rows: List[dict]) -> Dict[str, dict]:
    """Shape-level view over fields: one instance may contribute several."""
    fields: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        for field in row["fields"].values():
            fields[field["shape"]].append(field)
    out: Dict[str, dict] = {}
    for shape, members in sorted(fields.items()):
        labels = Counter(field["label"] for field in members)
        entry: Dict[str, Any] = {
            "fields": len(members),
            "mean_score": round(sum(f["score"] for f in members) / len(members), 4),
            "labels": {name: labels[name] for name in LABEL_PRIORITY if labels.get(name)},
        }
        for metric in ("key_f1", "value_accuracy", "prefix_ratio", "relative_error",
                       "median_relative_error", "precision", "recall"):
            values = [
                f["metrics"][metric] for f in members
                if f["label"] != "correct" and f["metrics"].get(metric) is not None
            ]
            if values:
                entry[f"failed_mean_{metric}"] = round(sum(values) / len(values), 4)
        out[shape] = entry
    return out


def build_report(
    run_dirs: Iterable[Path],
    *,
    evaluation_scope: str = "",
    source: str = "evaluation",
    float_tol: float = 1e-6,
) -> dict:
    run_dirs = list(run_dirs)
    rows_by_scope: Dict[str, List[dict]] = defaultdict(list)
    for run_dir in run_dirs:
        oracles: Dict[str, Any] = {}
        reported = _reported(run_dir)
        for scope, instance_id, rollout, path in _answer_files(run_dir, source):
            if evaluation_scope and scope != evaluation_scope:
                continue
            if instance_id not in oracles:
                oracles[instance_id] = _read_json(
                    run_dir / "instances" / instance_id / "oracle.json"
                )
            oracle = oracles[instance_id]
            answer = _read_json(path)
            if not isinstance(oracle, dict) or "oracle_answer" not in oracle or answer is None:
                continue
            row = decompose(oracle["oracle_answer"], answer, float_tol=float_tol)
            row.update({
                "run_dir": str(run_dir),
                "instance_id": instance_id,
                "category": oracle.get("question_kind", ""),
                "archetype": "+".join(sorted(oracle["oracle_answer"]))
                if isinstance(oracle["oracle_answer"], dict) else "",
            })
            if rollout:
                row["rollout"] = rollout
            else:
                # Answers left by an interrupted run are on disk but were never
                # counted in the reported accuracy.
                row["reported"] = instance_id in reported.get(scope, set())
            rows_by_scope[scope].append(row)

    scopes = {}
    for scope, rows in sorted(rows_by_scope.items()):
        scopes[scope] = {
            "summary": _summary(rows),
            "by_category": _group(rows, lambda row: [row["category"] or "unknown"]),
            "by_shape": _group(rows, lambda row: row["shapes"]),
            "by_archetype": _group(rows, lambda row: [row["archetype"] or "unknown"]),
            "fields_by_shape": _field_summary(rows),
            "instances": rows,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "method": "answer_error_decomposition",
        "source": source,
        "label_priority": list(LABEL_PRIORITY),
        "measure_fields": sorted(MEASURE_FIELDS),
        "run_dirs": [str(path) for path in run_dirs],
        "scopes": scopes,
    }


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
