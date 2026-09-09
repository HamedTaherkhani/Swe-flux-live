import json
from pathlib import Path

from repogen.cli import _refresh_frozen_perturbation_report


def test_perturbation_refresh_filters_active_without_rebinning(tmp_path: Path):
    source_run = tmp_path / "repo" / "run_1"
    source_run.mkdir(parents=True)
    source_report = tmp_path / "complexity_report.json"
    frozen_thresholds = {"combined": {"easy_max_score": 4.0}}
    source_report.write_text(json.dumps({
        "thresholds": frozen_thresholds,
        "instances": [{
            "run_dir": str(source_run),
            "instance_id": "original",
            "category": "S2_Loops",
            "answer_archetype": "loop_iteration_count",
        }],
    }))

    run_dir = tmp_path / "perturbation" / "repo"
    active = run_dir / "instances" / "candidate"
    active.mkdir(parents=True)
    (active / "oracle.json").write_text("{}")
    (run_dir / "perturbation_report.json").write_text(json.dumps({
        "source_run_dir": str(source_run),
        "complexity_objective": {"report": str(source_report)},
        "attempts": [
            {
                "original_id": "original",
                "new_id": "candidate",
                "category": "S2_Loops",
                "kept": True,
                "candidate_complexity_scores": {"combined": 7.0},
                "candidate_complexity_difficulties": {"combined": "very_hard"},
            },
            {
                "original_id": "original",
                "new_id": "screened_out",
                "category": "S2_Loops",
                "kept": True,
                "candidate_complexity_scores": {"combined": 5.0},
                "candidate_complexity_difficulties": {"combined": "medium"},
            },
        ],
    }))

    report = _refresh_frozen_perturbation_report(run_dir)

    assert report is not None
    assert report["thresholds"] == frozen_thresholds
    assert report["instance_count"] == 1
    assert report["instances"][0]["instance_id"] == "candidate"
    assert report["instances"][0]["difficulty"]["combined"] == "very_hard"
    assert report["methodology"]["binning"].startswith("thresholds frozen")
