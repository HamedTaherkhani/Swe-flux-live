"""Answer scoring. The comparison core is RepoBehave's evaluate_qa_answers.py,
copied verbatim (see that file's header); this adapter exposes the one call
the validation stage needs."""

from __future__ import annotations

from typing import Any, Tuple

from .evaluate_qa_answers import compare_values, pick_answer_payload


def score_answer(
    oracle_answer: Any, predicted: Any, float_tol: float = 1e-6
) -> Tuple[bool, str]:
    """Compare a predicted answer payload against the oracle answer using the
    benchmark's tolerant comparison rules. Returns (correct, reason)."""
    payload = pick_answer_payload(predicted)
    result = compare_values(
        expected=oracle_answer,
        pred=payload,
        key_name="root",
        path="$",
        float_tol=float_tol,
    )
    return result.ok, (result.reason or "")
