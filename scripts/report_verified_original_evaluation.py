#!/usr/bin/env python3
"""Rebuild Kimi evaluation statistics for verified original instances.

The accumulated evaluation reports can describe only the latest partial
invocation even when older per-instance answer folders remain on disk.  This
script therefore treats the filesystem artifacts as authoritative: it obtains
the original-instance inventory and intrinsic labels from complexity_report,
derives verification from Haiku/Fable solver rollouts, and re-scores every
available Kimi answer with RepoBehave's comparison implementation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from repogen.scoring import score_answer


VALIDATOR_FAMILIES = ("haiku", "fable")
METRICS = (
    "semantic_reasoning",
    "answer_construction",
    "repository_navigation",
    "combined",
)
DIFFICULTIES = ("easy", "medium", "hard", "very_hard")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def validation_evidence(run_dir: Path) -> dict[str, list[dict]]:
    """Successful approved-family solver runs, keyed by instance id."""
    report = read_json(run_dir / "validation_report.json", {}) or {}
    evidence: dict[str, list[dict]] = defaultdict(list)
    for run in report.get("runs", []):
        if run.get("validator") != "solver_agent":
            continue
        identity = " ".join(
            str(run.get(key, "")) for key in ("agent", "model", "scope")
        ).lower()
        if not any(family in identity for family in VALIDATOR_FAMILIES):
            continue
        for verdict in run.get("verdicts", []):
            instance_id = str(verdict.get("instance_id", ""))
            details = verdict.get("details", {}) or {}
            pass_count = int(details.get("pass_count", 0) or 0)
            if not (verdict.get("passed") or pass_count > 0) or not instance_id:
                continue
            evidence[instance_id].append({
                "scope": str(run.get("scope", "")),
                "model": str(run.get("model", "")),
                "passed_verdict": bool(verdict.get("passed")),
                "pass_count": max(pass_count, 1 if verdict.get("passed") else 0),
            })
    return dict(evidence)


def evaluation_failures(run_dir: Path) -> dict[str, str]:
    """Latest recorded Kimi failure reason, used when no answer file exists."""
    report = read_json(run_dir / "evaluation_report.json", {}) or {}
    failures: dict[str, str] = {}
    for run in report.get("runs", []):
        if run.get("scope") != "kimi/kimi-k3":
            continue
        for verdict in run.get("verdicts", []):
            instance_id = str(verdict.get("instance_id", ""))
            if instance_id and not verdict.get("passed"):
                failures[instance_id] = str(verdict.get("reason", ""))
    return failures


def aggregate(records: Iterable[dict]) -> dict:
    rows = list(records)
    correct = sum(bool(row["kimi_correct"]) for row in rows)
    answer_files = sum(bool(row["kimi_answer_present"]) for row in rows)
    total = len(rows)
    return {
        "total": total,
        "answer_files": answer_files,
        "missing_answer_files": total - answer_files,
        "correct": correct,
        "incorrect_or_unsolved": total - correct,
        "accuracy": round(correct / total, 6) if total else None,
    }


def grouped(records: list[dict], key) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        buckets[str(key(record))].append(record)
    return [
        {"group": name, **aggregate(members)}
        for name, members in sorted(buckets.items())
    ]


def difficulty_rows(records: list[dict], metric: str) -> list[dict]:
    by_label = {label: [] for label in DIFFICULTIES}
    for record in records:
        label = record.get("difficulty", {}).get(metric, "unknown")
        by_label.setdefault(label, []).append(record)
    return [
        {"difficulty": label, **aggregate(by_label[label])}
        for label in DIFFICULTIES
    ]


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)
    return "\n".join(lines)


def pct(value: Any) -> str:
    return "--" if value is None else f"{100 * float(value):.1f}%"


def build_markdown(report: dict) -> str:
    strict = report["strict_verified_evaluation"]
    overall = strict["overall"]
    lines = [
        "# Kimi evaluation on verified original instances",
        "",
        "## Inclusion and scoring policy",
        "",
        "- Original instances only; perturbation outputs are excluded.",
        "- Verified means at least one correct Haiku or Fable solver-agent rollout.",
        "- Every available `kimi/kimi-k3` `answer.json` is re-scored against the oracle with the benchmark comparator.",
        "- A verified instance with no usable Kimi answer remains in the denominator and is counted as incorrect/unsolved.",
        "- Unverified instances are excluded from the strict denominator.",
        "",
        "## Overall result",
        "",
        markdown_table(
            ["Original", "Verified", "Kimi answers", "Missing", "Correct", "Incorrect/unsolved", "Accuracy"],
            [[
                report["inventory"]["original_instances"],
                report["inventory"]["verified_instances"],
                overall["answer_files"],
                overall["missing_answer_files"],
                overall["correct"],
                overall["incorrect_or_unsolved"],
                pct(overall["accuracy"]),
            ]],
        ),
        "",
        "## By combined intrinsic difficulty",
        "",
        markdown_table(
            ["Difficulty", "Verified", "Answers", "Missing", "Correct", "Incorrect/unsolved", "Accuracy"],
            [[
                row["difficulty"].replace("_", " "), row["total"], row["answer_files"],
                row["missing_answer_files"], row["correct"], row["incorrect_or_unsolved"],
                pct(row["accuracy"]),
            ] for row in strict["by_difficulty"]["combined"]],
        ),
        "",
        "## By repository",
        "",
        markdown_table(
            ["Repository", "Verified", "Answers", "Missing", "Correct", "Incorrect/unsolved", "Accuracy"],
            [[
                row["group"], row["total"], row["answer_files"], row["missing_answer_files"],
                row["correct"], row["incorrect_or_unsolved"], pct(row["accuracy"]),
            ] for row in strict["by_repository"]],
        ),
        "",
        "## By category",
        "",
        markdown_table(
            ["Category", "Verified", "Answers", "Missing", "Correct", "Incorrect/unsolved", "Accuracy"],
            [[
                row["group"], row["total"], row["answer_files"], row["missing_answer_files"],
                row["correct"], row["incorrect_or_unsolved"], pct(row["accuracy"]),
            ] for row in strict["by_category"]],
        ),
        "",
        "## Missing Kimi outputs among verified instances",
        "",
    ]
    missing = strict["missing_kimi_answers"]
    if missing:
        lines.extend(
            f"- `{row['repository']}/{row['instance_id']}`: {row['kimi_reason']}"
            for row in missing
        )
    else:
        lines.append("None.")

    sensitivity = report["sensitivity_include_designated_llama_as_unsolved"]
    lines.extend([
        "",
        "## Sensitivity: force the five unverified LlamaFactory instances into the denominator as unsolved",
        "",
        "These five instances have no correct approved validation rollout, so this is not the strict verified-only result.",
        "",
        markdown_table(
            ["Denominator", "Correct", "Incorrect/unsolved", "Accuracy"],
            [[
                sensitivity["overall"]["total"], sensitivity["overall"]["correct"],
                sensitivity["overall"]["incorrect_or_unsolved"],
                pct(sensitivity["overall"]["accuracy"]),
            ]],
        ),
        "",
        "Forced-unsolved LlamaFactory instances:",
        "",
    ])
    lines.extend(f"- `{instance_id}`" for instance_id in sensitivity["forced_instance_ids"])
    lines.append("")
    return "\n".join(lines)


def build_report(complexity_path: Path) -> dict:
    complexity = read_json(complexity_path, {}) or {}
    source_records = complexity.get("instances", [])
    all_records: list[dict] = []

    by_run: dict[str, list[dict]] = defaultdict(list)
    for source in source_records:
        by_run[str(source.get("run_dir", ""))].append(source)

    for run_text, sources in sorted(by_run.items()):
        run_dir = Path(run_text)
        repo = run_dir.parent.name
        evidence = validation_evidence(run_dir)
        failures = evaluation_failures(run_dir)
        for source in sources:
            instance_id = str(source["instance_id"])
            oracle_path = run_dir / "instances" / instance_id / "oracle.json"
            answer_path = (
                run_dir / "evaluation" / "llm" / "kimi" / "kimi-k3"
                / instance_id / "answer.json"
            )
            oracle = read_json(oracle_path)
            answer = read_json(answer_path)
            answer_present = answer is not None and answer_path.is_file()
            correct = False
            reason = failures.get(instance_id, "")
            if not isinstance(oracle, dict) or "oracle_answer" not in oracle:
                reason = "oracle missing or malformed"
            elif answer_present:
                correct, score_reason = score_answer(oracle["oracle_answer"], answer)
                reason = "matched oracle" if correct else (score_reason or "answer mismatch")
            elif not reason:
                reason = "no Kimi answer.json"

            all_records.append({
                "repository": repo,
                "run_dir": run_text,
                "instance_id": instance_id,
                "category": source.get("category", ""),
                "answer_archetype": source.get("answer_archetype", ""),
                "difficulty": source.get("difficulty", {}),
                "scores": source.get("scores", {}),
                "verified": instance_id in evidence,
                "validation_evidence": evidence.get(instance_id, []),
                "kimi_answer_present": answer_present,
                "kimi_answer_path": str(answer_path) if answer_present else None,
                "kimi_correct": bool(correct),
                "kimi_reason": reason,
            })

    strict_records = [record for record in all_records if record["verified"]]
    unverified_records = [record for record in all_records if not record["verified"]]
    forced_llama = sorted(
        record["instance_id"] for record in unverified_records
        if record["repository"] == "llama_factory" and not record["kimi_answer_present"]
    )
    sensitivity_records = strict_records + [
        record for record in unverified_records
        if record["repository"] == "llama_factory"
        and record["instance_id"] in forced_llama
    ]

    strict = {
        "overall": aggregate(strict_records),
        "by_repository": grouped(strict_records, lambda row: row["repository"]),
        "by_category": grouped(strict_records, lambda row: row["category"]),
        "by_difficulty": {
            metric: difficulty_rows(strict_records, metric) for metric in METRICS
        },
        "missing_kimi_answers": [
            record for record in strict_records if not record["kimi_answer_present"]
        ],
        "instances": strict_records,
    }
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_complexity_report": str(complexity_path),
        "evaluation_scope": "kimi/kimi-k3",
        "policy": {
            "original_instances_only": True,
            "verification": "at least one correct Haiku or Fable solver-agent rollout",
            "available_answers": "re-scored from per-instance answer.json with RepoBehave comparator",
            "missing_verified_answer": "counted as incorrect/unsolved",
            "unverified": "excluded from strict evaluation",
        },
        "inventory": {
            "original_instances": len(all_records),
            "verified_instances": len(strict_records),
            "unverified_instances": len(unverified_records),
            "unverified_by_repository": grouped(unverified_records, lambda row: row["repository"]),
        },
        "strict_verified_evaluation": strict,
        "sensitivity_include_designated_llama_as_unsolved": {
            "note": (
                "Not a strict verified-only result: these LlamaFactory instances "
                "have no correct approved validator rollout."
            ),
            "forced_instance_ids": forced_llama,
            "overall": aggregate(sensitivity_records),
            "by_difficulty": {
                metric: difficulty_rows(sensitivity_records, metric) for metric in METRICS
            },
        },
        "unverified_instances": unverified_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--complexity-report", type=Path, default=Path("out/complexity_report.json")
    )
    parser.add_argument(
        "--json-output", type=Path,
        default=Path("out/original_verified_kimi_evaluation_report.json"),
    )
    parser.add_argument(
        "--markdown-output", type=Path,
        default=Path("out/original_verified_kimi_evaluation_report.md"),
    )
    args = parser.parse_args()

    report = build_report(args.complexity_report)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(build_markdown(report), encoding="utf-8")

    overall = report["strict_verified_evaluation"]["overall"]
    print(
        f"verified originals: {overall['total']}; correct: {overall['correct']}; "
        f"incorrect/unsolved: {overall['incorrect_or_unsolved']}; "
        f"accuracy: {overall['accuracy']:.4%}"
    )
    print(args.json_output)
    print(args.markdown_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
